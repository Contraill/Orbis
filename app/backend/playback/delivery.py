import logging

import httpx

from playback.delivery_policy import delivery_policy
from playback.hls import read_manifest, resource_url, rewrite_manifest
from playback.source_sessions import source_sessions
from playback.upstream import UpstreamRejected, new_http_client, open_upstream
from providers.source_policy import source_expiry_status


logger = logging.getLogger(__name__)


class DeliveryUnavailable(ValueError):
    pass


class DeliveryBroker:
    def issue(self, profile_id, content_key, source, audience=""):
        from playback.capabilities import current_capabilities, request_client
        from playback.delivery_policy import DeliveryPlan
        caps = current_capabilities()
        plan = delivery_policy.choose(source, audience)
        if caps is not None and source.protocol == "hls":
            plan = DeliveryPlan(plan.relay | {"root", "manifest"})
        session = source_sessions.issue(
            profile_id, content_key, source, audience=audience,
            plan=plan,
        )
        session.context["capabilities"] = caps
        ctx = request_client.get()
        if ctx:
            session.context["client_session_id"] = ctx["id"]
        return session

    def client_url(self, session):
        return resource_url(session, session.resources["root"])

    def client_subtitles(self, session):
        tracks = []
        for track in session.source.subtitle_tracks:
            if track.kind == "external" and track.url and "subtitle" in session.plan.relay:
                resource = source_sessions.register(session, session.resources["root"], track.url, "subtitle")
                track = track.model_copy(update={"url": resource_url(session, resource)})
            tracks.append(track)
        return tracks

    async def _probe(self, session, resource):
        client = new_http_client()
        response = None
        try:
            manifest = session.source.protocol == "hls" and resource.kind in {"root", "manifest"}
            response, final_url = await open_upstream(
                client, session.source, resource.url,
                range_headers=None if manifest else {"Range": "bytes=0-0"},
            )
            if response.status_code not in {200, 206}:
                raise DeliveryUnavailable("Source unavailable through server egress")
            if manifest:
                rewrite_manifest(session, resource, final_url, await read_manifest(response))
        finally:
            if response is not None:
                await response.aclose()
            await client.aclose()

    async def recover(self, session, failure):
        if failure.category != "network" or source_expiry_status(session.source) == "expired":
            raise DeliveryUnavailable("Delivery recovery is not applicable")
        if session.source.protocol not in {"hls", "http"}:
            raise DeliveryUnavailable("Delivery recovery is not supported")
        plan = session.plan
        kind = failure.resource_type
        if session.source.protocol == "http":
            target = "root"
        elif kind == "manifest":
            target = "root" if "root" not in plan.relay else "manifest"
        elif kind in {"segment", "init", "key", "subtitle"}:
            target = kind
        else:
            raise DeliveryUnavailable("Insufficient delivery failure evidence")
        if target in plan.relay:
            raise DeliveryUnavailable("This resource already uses server delivery")
        if not source_sessions.claim_recovery(session, target):
            raise DeliveryUnavailable("Recovery for this session was already attempted")
        try:
            # The probe target is always server-issued; the client supplies no URL.
            if target == "root":
                candidate = session.resources["root"]
            else:
                await self._probe(session, session.resources["root"])
                candidates = [r for r in source_sessions.resources(session) if r.kind == target]
                if not candidates and target != "manifest":
                    manifests = [r for r in source_sessions.resources(session) if r.kind == "manifest"]
                    for resource in manifests[:3]:
                        await self._probe(session, resource)
                    candidates = [r for r in source_sessions.resources(session) if r.kind == target]
                if not candidates:
                    raise DeliveryUnavailable("No attested resource to probe")
                candidate = candidates[0]
            await self._probe(session, candidate)
        except (httpx.HTTPError, OSError, UpstreamRejected) as exc:
            logger.info("delivery_probe_failed session=%s reason=%s", session.session_id[:8], type(exc).__name__)
            raise DeliveryUnavailable("Delivery recovery failed") from exc

        kinds = [target]
        if target not in {"root", "manifest", "subtitle"}:
            kinds.append("manifest")
        next_plan = plan.include(*kinds)
        delivery_policy.observe(session.source, session.audience, next_plan)
        logger.info(
            "delivery_escalated session=%s resource=%s client_status=%s relay=%s",
            session.session_id[:8], target, failure.http_status, sorted(next_plan.relay),
        )
        replacement = source_sessions.issue(
            session.profile_id, session.content_key, session.source,
            plan=next_plan, audience=session.audience,
        )
        replacement.evidence.extend([*session.evidence, {
            "resource_type": target,
            "client_http_status": failure.http_status,
            "client_error_code": failure.code,
            "server_probe": "success",
        }])
        replacement.context.update(session.context)
        return replacement


delivery_broker = DeliveryBroker()
