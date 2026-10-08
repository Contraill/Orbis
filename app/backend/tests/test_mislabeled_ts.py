"""Narrow relay handling for MPEG-TS mislabeled as active HTML content."""
import unittest
from unittest.mock import patch

import httpx

from playback.delivery_policy import ALL_RESOURCES, DeliveryPlan
from playback.media_types import SNIFF_BYTES, media_type
from playback.source_sessions import source_sessions
from test_playback_hardening import HardeningTestCase, source


PACKET = b"\x47\x00\x00\x10" + b"\x00" * 184
TS = PACKET * 7
FMP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 1400


class BodyStream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body[:200]
        yield self.body[200:]


class MislabeledTSTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        self.dns = patch("playback.upstream.public_address", return_value="93.184.216.34")
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def resource_url(self):
        session = source_sessions.issue(
            self.profile.id, "movie:1", source("generic", "master"),
            plan=DeliveryPlan(ALL_RESOURCES), audience="test-client",
        )
        resource = source_sessions.register(
            session, session.resources["root"], "https://media.example/segment.ts", "segment",
        )
        return f"/api/playback/sources/{session.session_id}/{resource.resource_id}"

    def fetch(self, body, content_type, *, status=200):
        def factory():
            return httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status, headers={"Content-Type": content_type}, stream=BodyStream(body),
                )
            ))
        with patch("api.playback_proxy._new_http_client", side_effect=factory):
            return self.client.get(self.resource_url())

    def test_html_labeled_ts_is_normalized(self):
        response = self.fetch(TS, "text/html; charset=UTF-8")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp2t")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.content, TS)

    def test_real_html_stays_rejected(self):
        self.assertEqual(self.fetch(b"<!doctype html><html>Error</html>", "text/html").status_code, 502)

    def test_random_binary_stays_rejected(self):
        self.assertEqual(self.fetch(bytes(range(256)) * 6, "text/html").status_code, 502)

    def test_incomplete_or_corrupt_ts_stays_rejected(self):
        self.assertIsNone(media_type(TS[:SNIFF_BYTES - 1]))
        broken = bytearray(TS)
        broken[4 * 188] = 0
        self.assertEqual(self.fetch(bytes(broken), "text/html").status_code, 502)

    def test_correctly_labeled_ts_is_unchanged(self):
        response = self.fetch(TS, "video/mp2t")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp2t")
        self.assertEqual(response.content, TS)

    def test_existing_fmp4_sniff_still_works(self):
        response = self.fetch(FMP4, "image/png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(response.content, FMP4)

    def test_fmp4_labeled_html_is_still_rejected(self):
        self.assertEqual(self.fetch(FMP4, "text/html").status_code, 502)


if __name__ == "__main__":
    unittest.main()
