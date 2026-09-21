import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx

from playback.delivery import DeliveryBroker, DeliveryUnavailable
from playback.delivery_policy import ALL_RESOURCES, DeliveryPlan, DeliveryPolicy, delivery_policy
from playback.hls import MAX_MANIFEST_BYTES, read_manifest, rewrite_manifest
from playback.schemas import PlaybackFailure
from playback.source_sessions import SourceSessionExpired, source_sessions
from playback.upstream import UpstreamRejected, open_upstream, origin, public_address
from providers.resolution import ResolutionBroker, ResolutionCapabilityUnavailable
from providers.schemas import DeliveryHints
from test_playback_hardening import HardeningTestCase, SequencedProvider, source


MASTER = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500000\nlow/index.m3u8?token=signed\n'
VARIANT = (
    '#EXTM3U\n#EXT-X-TARGETDURATION:10\n'
    '#EXT-X-KEY:METHOD=AES-128,URI="../key.bin?secret=key"\n'
    '#EXT-X-MAP:URI="init.mp4",BYTERANGE="100@0"\n'
    '#EXTINF:10,\n#EXT-X-BYTERANGE:100@100\nchunk.ts\n#EXT-X-ENDLIST\n'
)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class DeliveryTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        delivery_policy.clear()
        self.requests = []
        self.bodies = []
        self.patches = [
            patch("playback.upstream.public_address", return_value="93.184.216.34"),
            patch("playback.delivery.new_http_client", side_effect=self.client_factory),
            patch("api.playback_proxy._new_http_client", side_effect=self.client_factory),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def client_factory(self):
        def handler(request):
            self.requests.append(request)
            if request.url.path.endswith("/master.m3u8"):
                return httpx.Response(200, text=MASTER)
            if request.url.path.endswith("index.m3u8"):
                return httpx.Response(200, text=VARIANT)
            body = Chunks(b"ab", b"cd")
            self.bodies.append(body)
            return httpx.Response(206, headers={
                "Content-Type": "video/mp2t", "Content-Length": "4",
                "Content-Range": "bytes 100-103/200", "Accept-Ranges": "bytes",
                "X-Secret": "hidden", "Set-Cookie": "hidden=value",
            }, stream=body)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def entry(self, plan=None, headers=None):
        return source_sessions.issue(
            self.profile.id, "movie:1", source("generic", "master", headers=headers),
            plan=plan, audience="client-one",
        )

    def test_master_only_then_manifests_then_media_on_evidence(self):
        broker = DeliveryBroker()
        entry = self.entry()
        self.assertEqual(broker.client_url(entry), entry.source.url)
        failure = PlaybackFailure(category="network", resource_type="manifest", http_status=403)
        first = asyncio.run(broker.recover(entry, failure))
        self.assertEqual(first.plan.relay, {"root"})
        master = self.client.get(broker.client_url(first))
        self.assertEqual(master.status_code, 200)
        self.assertIn("https://media.example/low/index.m3u8?token=signed", master.text)

        second = asyncio.run(broker.recover(first, failure))
        master = self.client.get(broker.client_url(second))
        variant_url = master.text.splitlines()[-1]
        self.assertTrue(variant_url.startswith("/api/playback/sources/"))
        variant = self.client.get(variant_url)
        self.assertIn("https://media.example/low/chunk.ts", variant.text)
        self.assertIn("https://media.example/key.bin?secret=key", variant.text)
        self.assertEqual(second.plan.relay, {"root", "manifest"})

        third = asyncio.run(broker.recover(second, PlaybackFailure(category="network", resource_type="segment")))
        self.assertEqual(third.plan.relay, {"root", "manifest", "segment"})
        master = self.client.get(broker.client_url(third))
        variant = self.client.get(master.text.splitlines()[-1])
        segment_url = next(line for line in variant.text.splitlines() if line.startswith("/api/"))
        response = self.client.get(segment_url, headers={"Range": "bytes=100-103", "Authorization": "client-secret"})
        self.assertEqual(response.content, b"abcd")
        self.assertEqual(response.headers["content-range"], "bytes 100-103/200")
        self.assertEqual(self.requests[-1].headers["range"], "bytes=100-103")
        self.assertNotIn("authorization", self.requests[-1].headers)
        self.assertTrue(self.bodies[-1].closed)
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("x-secret", response.headers)
        with self.assertRaises(DeliveryUnavailable):
            asyncio.run(broker.recover(third, PlaybackFailure(category="network", resource_type="segment")))

    def test_full_relay_rewrites_key_init_segments_and_hides_headers(self):
        entry = self.entry(DeliveryPlan(ALL_RESOURCES), {"Authorization": "Bearer secret"})
        root = entry.resources["root"]
        text = rewrite_manifest(entry, root, "https://media.example/low/index.m3u8", VARIANT)
        self.assertNotIn("media.example", text)
        self.assertIn('BYTERANGE="100@0"', text)
        self.assertIn("#EXT-X-BYTERANGE:100@100", text)
        for item in source_sessions.resources(entry):
            if item.kind == "root":
                continue
            response = self.client.get(f"/api/playback/sources/{entry.session_id}/{item.resource_id}")
            self.assertEqual(response.status_code, 206)
            self.assertNotIn("secret", response.text)
            self.assertEqual(self.requests[-1].headers["authorization"], "Bearer secret")
        self.assertEqual({r.kind for r in source_sessions.resources(entry)}, {"root", "key", "init", "segment"})

    def test_unknown_resources_extra_query_expiry_and_private_ancestry(self):
        entry = self.entry(DeliveryPlan(ALL_RESOURCES))
        path = f"/api/playback/sources/{entry.session_id}"
        self.assertEqual(self.client.get(path + "/unknown").status_code, 404)
        self.assertEqual(self.client.get(path + "?url=http://127.0.0.1").status_code, 400)
        for uri in ("http://127.0.0.1/private", "https://evil.example/seg.ts", "file:///etc/passwd", "http://169.254.169.254/"):
            with self.subTest(uri=uri), self.assertRaises(UpstreamRejected):
                rewrite_manifest(entry, entry.resources["root"], entry.source.url, f"#EXTM3U\n{uri}\n")
        with self.assertRaises(SourceSessionExpired):
            expiring = source("generic", "soon", expires_at=datetime.now(timezone.utc) + timedelta(seconds=1))
            issued = source_sessions.issue(self.profile.id, "movie:2", expiring)
            source_sessions.get(issued.session_id, for_proxy=True, now=datetime.now(timezone.utc) + timedelta(seconds=2))

    def test_recovery_api_preserves_state_and_does_not_resolve_again(self):
        provider = SequencedProvider("generic", 10, [[source("generic", "master")]])
        all_patch, get_patch = self.provider_patches([provider])
        path = f"/api/playback/profiles/{self.profile.id}/movie/1"
        with all_patch, get_patch:
            resolved = self.client.post(path + "/resolve").json()
            recovered = self.client.post(path + "/recover", json={
                "source_session_id": resolved["source_session_id"],
                "position_seconds": 127, "duration_seconds": 800,
                "preferred_audio_language": "tr", "preferred_audio_kind": "dub",
                "preferred_audio_track_id": "audio-tr-dub", "subtitles_enabled": True,
                "preferred_subtitle_language": "tr", "preferred_subtitle_track_id": "subtitle-tr",
                "failure": {"category": "network", "resource_type": "manifest", "http_status": 403},
            })
            self.assertEqual(recovered.status_code, 200, recovered.text)
            body = recovered.json()
            self.assertEqual(body["state"]["resume_position_seconds"], 127)
            self.assertEqual(body["state"]["duration_seconds"], 800)
            self.assertEqual(body["selected_audio"]["track"]["track_id"], "audio-tr-dub")
            self.assertTrue(body["selected_subtitles"]["enabled"])
            self.assertEqual(provider.calls, 1)
            self.assertNotIn("media.example", recovered.text)
            refresh = self.client.post(path + "/refresh", json={
                "source_session_id": body["source_session_id"], "position_seconds": 130,
                "preferred_audio_language": "tr", "subtitles_enabled": True,
            })
            self.assertEqual(refresh.status_code, 200, refresh.text)
            self.assertTrue(refresh.json()["selected_source"]["url"].startswith("/api/"))
            self.assertEqual(provider.calls, 2)

    def test_recovery_scope_and_schema_rejects_client_targets(self):
        entry = self.entry()
        path = f"/api/playback/profiles/{self.profile.id}/movie/2/recover"
        data = {"source_session_id": entry.session_id, "failure": {"category": "network", "resource_type": "manifest"}}
        self.assertEqual(self.client.post(path, json=data).status_code, 404)
        data["failure"]["url"] = "http://127.0.0.1"
        self.assertEqual(self.client.post(path, json=data).status_code, 422)

    def test_codec_failure_goes_to_provider_fallback_without_relay(self):
        first = SequencedProvider("first", 10, [[source("first", "master")]])
        second = SequencedProvider("second", 20, [[source("second", "master")]])
        all_patch, get_patch = self.provider_patches([first, second])
        path = f"/api/playback/profiles/{self.profile.id}/movie/1"
        with all_patch, get_patch:
            initial = self.client.post(path + "/resolve").json()
            response = self.client.post(path + "/recover", json={
                "source_session_id": initial["source_session_id"],
                "position_seconds": 95,
                "failure": {"category": "media", "code": 3016},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["resolution"]["selected_provider_id"], "second")
        self.assertEqual(response.json()["state"]["position_seconds"], 95)
        self.assertEqual(self.requests, [])

    def test_public_http_is_direct_and_network_failure_can_relay(self):
        item = source("generic", "movie", protocol="http")
        broker = DeliveryBroker()
        initial = broker.issue(self.profile.id, "movie:1", item)
        self.assertEqual(broker.client_url(initial), item.url)
        replacement = asyncio.run(broker.recover(initial, PlaybackFailure(category="network", resource_type="segment")))
        self.assertTrue(broker.client_url(replacement).startswith("/api/"))
        self.assertEqual(self.requests[-1].headers["range"], "bytes=0-0")
        self.assertTrue(self.bodies[-1].closed)

    def test_hls_headers_force_relay_and_are_absent_from_session_and_diagnostics(self):
        provider = SequencedProvider("secure", 10, [[source("secure", "master", headers={"Authorization": "top-secret"})]])
        all_patch, get_patch = self.provider_patches([provider])
        with all_patch, get_patch:
            response = self.client.post(f"/api/playback/profiles/{self.profile.id}/movie/1/resolve")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("top-secret", response.text)
        self.assertNotIn("media.example", response.text)
        diagnostic = self.client.get("/api/admin/playback/delivery")
        self.assertNotIn("top-secret", diagnostic.text)
        self.assertNotIn("media.example", diagnostic.text)
        self.assertEqual(diagnostic.json()[-1]["mode"], "full")

    def test_expired_recover_reresolves_current_provider(self):
        provider = SequencedProvider("generic", 10, [[source("generic", "master")]])
        all_patch, get_patch = self.provider_patches([provider])
        path = f"/api/playback/profiles/{self.profile.id}/movie/1"
        with all_patch, get_patch:
            initial = self.client.post(path + "/resolve").json()
            entry = source_sessions.get(initial["source_session_id"])
            entry.source.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            response = self.client.post(path + "/recover", json={
                "source_session_id": entry.session_id,
                "position_seconds": 150,
                "failure": {"category": "network", "resource_type": "manifest"},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(response.json()["state"]["position_seconds"], 150)
        self.assertEqual(self.requests, [])


class PolicyAndSecurityTests(unittest.TestCase):
    def test_cache_is_client_scoped_and_expires_without_sliding(self):
        policy = DeliveryPolicy()
        item = source("generic", "master")
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        policy.observe(item, "remote", DeliveryPlan(frozenset({"root"})), now=now)
        self.assertEqual(policy.choose(item, "local", now=now).mode, "direct")
        self.assertEqual(policy.choose(item, "remote", now=now).relay, {"root"})
        policy.observe(item, "remote", DeliveryPlan(ALL_RESOURCES), now=now + timedelta(minutes=14))
        self.assertEqual(policy.choose(item, "remote", now=now + timedelta(minutes=16)).mode, "direct")
        item.headers = {"Cookie": "secret"}
        self.assertEqual(policy.choose(item).mode, "full")
        item.headers = {}
        item.protocol = "http"
        self.assertEqual(policy.choose(item).mode, "direct")

    def test_dns_rebinding_and_non_public_literals_are_rejected(self):
        for url in ("http://127.0.0.1/", "http://[::1]/", "http://100.64.0.10/", "http://169.254.169.254/", "https://user:pass@example.com/", "https://example.com:22/"):
            with self.subTest(url=url), self.assertRaises(UpstreamRejected):
                origin(url)
        async def run():
            loop = asyncio.get_running_loop()
            with patch.object(loop, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
                with self.assertRaises(UpstreamRejected):
                    await public_address("https://public-looking.example/")
        asyncio.run(run())

    def test_redirect_is_pinned_and_credentials_do_not_cross_origins(self):
        requests = []
        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(302, headers={"Location": "https://cdn.example/segment.ts", "Set-Cookie": "leak=secret"})
            return httpx.Response(200, stream=Chunks(b"media"))
        async def run():
            item = source("generic", "master", headers={"Authorization": "secret", "Cookie": "cookie=secret"})
            item.delivery = DeliveryHints(resource_origins=["https://cdn.example"])
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch("playback.upstream.public_address", return_value="93.184.216.34"):
                    response, final = await open_upstream(client, item, item.url)
                    await response.aclose()
            self.assertEqual(final, "https://cdn.example/segment.ts")
        asyncio.run(run())
        self.assertEqual(requests[0].url.host, "93.184.216.34")
        self.assertEqual(requests[0].extensions["sni_hostname"], "media.example")
        self.assertEqual(requests[1].headers["host"], "cdn.example")
        self.assertNotIn("authorization", requests[1].headers)
        self.assertNotIn("cookie", requests[1].headers)

    def test_manifest_size_and_invalid_body_are_bounded(self):
        async def run():
            for chunks in ((b"<html>403</html>",), (b"#EXTM3U\n", b"x" * MAX_MANIFEST_BYTES)):
                response = httpx.Response(200, stream=Chunks(*chunks))
                with self.assertRaises(UpstreamRejected):
                    await read_manifest(response)
                await response.aclose()
        asyncio.run(run())

    def test_unsafe_redirect_is_never_requested(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/metadata"})
        async def run():
            item = source("generic", "master")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch("playback.upstream.public_address", return_value="93.184.216.34"):
                    with self.assertRaises(UpstreamRejected):
                        await open_upstream(client, item, item.url)
        asyncio.run(run())
        self.assertEqual(len(requests), 1)

    def test_auto_resolution_escalates_only_on_rejection(self):
        broker = ResolutionBroker()
        modes = []
        def factory(mode):
            modes.append(mode)
            return httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(403 if mode == "server_http" else 200)
            ))
        async def run():
            with patch.object(broker, "_new", side_effect=factory):
                self.assertEqual((await broker.get("https://example.com/")).status_code, 200)
        asyncio.run(run())
        self.assertEqual(modes, ["server_http", "browser_http"])

    def test_resolution_cookie_sessions_and_uninstalled_hooks(self):
        broker = ResolutionBroker()
        cookies = []
        def handler(request):
            cookies.append(request.headers.get("cookie"))
            return httpx.Response(200, text="ok", headers={"Set-Cookie": "session=one"})
        def factory(mode):
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async def run():
            with patch.object(broker, "_new", side_effect=factory):
                async with broker.session():
                    await broker.get("https://example.com/", mode="browser_http")
                    await broker.get("https://example.com/next", mode="browser_http")
                async with broker.session():
                    await broker.get("https://example.com/", mode="browser_http")
            for mode in ("real_browser", "client_egress"):
                with self.assertRaises(ResolutionCapabilityUnavailable):
                    await broker.get("https://example.com/", mode=mode)
        asyncio.run(run())
        self.assertEqual(cookies, [None, "session=one", None])
