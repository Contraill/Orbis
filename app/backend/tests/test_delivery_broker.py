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
    def test_long_multiaudio_film_keeps_all_advertised_playlists_reachable(self):
        entry = self.entry(DeliveryPlan(ALL_RESOURCES))
        master = '#EXTM3U\n' + ''.join(
            f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="{name}",URI="{name}.m3u8"\n'
            for name in ('turkish', 'original')
        ) + '#EXT-X-STREAM-INF:BANDWIDTH=1000000,AUDIO="audio"\nvideo.m3u8\n'
        rewrite_manifest(entry, entry.resources['root'], entry.source.url, master)
        children = [resource for resource in entry.resources.values() if resource.kind == 'manifest']
        for child in children:
            playlist = '#EXTM3U\n' + ''.join(
                f'#EXTINF:6,\n{child.resource_id}-segment-{index}.ts\n'
                for index in range(1760)
            )
            rewrite_manifest(entry, child, child.url, playlist)
        self.assertEqual(len(entry.resources), 1 + 3 + 3 * 1760)

    def test_mislabeled_ts_is_streamed_unchanged_and_head_range_are_consistent(self):
        body = (b'\x47' + b'\x00' * 187) * 4
        requests = []
        def handler(request):
            requests.append(request)
            headers = {'Content-Type':'application/x-mpegURL', 'Content-Length':str(len(body)), 'Accept-Ranges':'bytes'}
            if request.method == 'HEAD':
                return httpx.Response(200, headers=headers)
            data = body
            status = 200
            if request.headers.get('range'):
                first, last = map(int, request.headers['range'].removeprefix('bytes=').split('-'))
                data = body[first:last + 1]
                status = 206
                headers.update({'Content-Length':str(len(data)), 'Content-Range':f'bytes {first}-{last}/{len(body)}'})
            return httpx.Response(status, headers=headers, stream=Chunks(data[:190], data[190:]))
        def entry_url():
            entry = self.entry(DeliveryPlan(ALL_RESOURCES))
            resource = source_sessions.register(entry, entry.resources['root'], 'https://media.example/part.png', 'segment')
            return f'/api/playback/sources/{entry.session_id}/{resource.resource_id}'
        with patch('api.playback_proxy._new_http_client', side_effect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))):
            url = entry_url()
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, body)
            self.assertEqual(response.headers['content-type'], 'video/mp2t')
            response = self.client.head(url)
            self.assertEqual(response.headers['content-type'], 'video/mp2t')
            self.assertEqual(response.content, b'')
            self.assertEqual(len(requests), 2)  # HEAD reuses the attested MIME, no repeated probe.
            response = self.client.get(entry_url(), headers={'Range':'bytes=188-375'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, body[188:376])
            self.assertEqual(response.headers['content-range'], 'bytes 188-375/752')
            self.assertEqual(response.headers['content-type'], 'video/mp2t')
            self.assertEqual(requests[-1].headers['range'], 'bytes=0-563')
            response = self.client.get(entry_url(), headers={'Range':'bytes=0-63'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, body[:64])
            self.assertEqual(response.headers['content-range'], 'bytes 0-63/752')
            self.assertEqual(response.headers['content-type'], 'video/mp2t')
            response = self.client.head(entry_url())
            self.assertEqual(response.headers['content-type'], 'video/mp2t')
            self.assertEqual(response.headers['content-length'], str(len(body)))

    def test_mislabeled_non_media_fails_closed(self):
        entry = self.entry(DeliveryPlan(ALL_RESOURCES))
        resource = source_sessions.register(entry, entry.resources['root'], 'https://media.example/part.png', 'segment')
        def factory():
            return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
                200, headers={'Content-Type':'application/x-mpegURL'}, stream=Chunks(b'<html>not media</html>'),
            )))
        with patch('api.playback_proxy._new_http_client', side_effect=factory):
            response = self.client.get(f'/api/playback/sources/{entry.session_id}/{resource.resource_id}')
        self.assertEqual(response.status_code, 502)

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
        self.assertEqual(self.client.get("/api/admin/playback/delivery").status_code,401)
        from main import app
        from core.auth import require_owner
        app.dependency_overrides[require_owner] = lambda: self.profile
        try:
            diagnostic = self.client.get("/api/admin/playback/delivery")
        finally:
            app.dependency_overrides.pop(require_owner,None)
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
    def test_explicit_origin_headers_never_leak_across_redirects(self):
        requests = []
        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(302, headers={"Location": "https://cdn.example/segment"})
            if len(requests) == 2:
                return httpx.Response(302, headers={"Location": "https://other.example/segment"})
            return httpx.Response(206, stream=Chunks(b"media"))
        async def run():
            item = source("generic", "master", headers={"Cookie": "secret", "Authorization": "secret"})
            item.delivery = DeliveryHints(
                resource_origins=["https://cdn.example", "https://other.example"],
                resource_headers={"https://cdn.example": {"User-Agent": "Approved client", "Referer": "https://embed.example/"}},
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch("playback.upstream.public_address", return_value="93.184.216.34") as dns:
                    response, _ = await open_upstream(client, item, item.url, range_headers={"Range":"bytes=0-3"})
                    await response.aclose()
                    self.assertEqual(dns.call_count, 3)
        asyncio.run(run())
        self.assertEqual(requests[1].headers['referer'], 'https://embed.example/')
        self.assertEqual(requests[1].headers['user-agent'], 'Approved client')
        for request in requests[1:]:
            self.assertNotIn('cookie', request.headers)
            self.assertNotIn('authorization', request.headers)
            self.assertEqual(request.headers['range'], 'bytes=0-3')
        self.assertNotIn('referer', requests[2].headers)
        self.assertNotEqual(requests[2].headers.get('user-agent'), 'Approved client')

    def test_origin_policy_is_bounded_exact_and_non_secret(self):
        from pydantic import ValidationError
        invalid = [
            {'resource_origins':['https://*.example']},
            {'resource_origins':['https://cdn.example/path']},
            {'resource_origins':['https://user:pass@cdn.example']},
            {'resource_origins':[f'https://cdn{i}.example' for i in range(65)]},
            {'resource_headers':{'https://cdn.example':{'Referer':'https://embed.example/'}}},
        ]
        for header in ('Cookie', 'Authorization', 'Host', 'Origin', 'X-Secret'):
            invalid.append({'resource_origins':['https://cdn.example'], 'resource_headers':{'https://cdn.example':{header:'secret'}}})
        invalid.append({'resource_origins':['https://cdn.example'], 'resource_headers':{'https://cdn.example':{'Referer':'good\r\nCookie: secret'}}})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DeliveryHints(**value)
        policy = DeliveryHints(resource_origins=[f'https://cdn{i}.example' for i in range(25)])
        self.assertEqual(len(policy.resource_origins), 25)

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
        for url in ("http://127.0.0.1/", "http://[::1]/", "http://100.64.0.1/", "http://169.254.169.254/", "https://user:pass@example.com/", "https://example.com:22/"):
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
