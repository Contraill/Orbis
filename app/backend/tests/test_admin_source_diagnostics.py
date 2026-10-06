import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from api.admin_providers import diagnostic_result
from db.models.profile import Profile
from providers.schemas import AudioTrack, PlaybackResolution, SubtitleTrack
from test_playback_hardening import source


class AdminSourceDiagnosticsTests(unittest.TestCase):
    def test_safe_source_metadata_and_profile_order(self):
        preferred = source("sample", "preferred", quality="1080p")
        preferred.source_id = "first"
        preferred.source_label = "Preferred"
        preferred.audio_tracks = [AudioTrack(language="tr", kind="dub", track_id="private-id")]
        preferred.subtitle_tracks = [SubtitleTrack(language="tr", kind="manifest", track_id="private-subtitle")]
        fallback = source("sample", "fallback", quality="720p")
        fallback.source_id = "second"
        fallback.audio_tracks = [AudioTrack(language="en", kind="original", track_id="other-private-id")]
        fallback.subtitle_tracks = []
        profile = Profile(name="Owner", preferred_audio_language="tr", preferred_subtitle_language="tr", subtitles_enabled=True)
        response = httpx.Response(200, content=b"#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x816\nvideo.m3u8\n", request=httpx.Request("GET", "https://media.example/master.m3u8"))
        with patch("api.admin_providers.open_upstream", new=AsyncMock(return_value=(response, "https://media.example/master.m3u8"))):
            result = asyncio.run(diagnostic_result(PlaybackResolution(
                selected_provider_id="sample", sources=[fallback, preferred], attempts=[],
            ), profile))
        self.assertEqual([item.source_id for item in result.sources], ["first", "second"])
        self.assertEqual(result.sources[0].status, "reachable")
        self.assertEqual(result.sources[0].quality_classes, ["1080p"])
        self.assertEqual(result.sources[0].audio_languages, ["tr"])
        self.assertEqual(result.sources[0].audio_kinds, ["dub"])
        self.assertEqual(result.sources[0].subtitle_languages, ["tr"])
        serialized = result.model_dump_json()
        for secret in ("media.example", "private-id", "private-subtitle", "https://"):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
