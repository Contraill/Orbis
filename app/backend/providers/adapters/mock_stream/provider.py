from providers.contract import MediaProvider
from providers.schemas import (
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderSearchResult,
)


class MockStreamProvider(MediaProvider):
    id = "mock-stream"
    name = "Mock Stream"
    default_enabled = True
    default_priority = 100

    capabilities = ProviderCapabilities(
        movie=True,
        episode=True,
        protocols=["hls"],
    )

    async def health_check(self) -> ProviderHealthResult:
        return ProviderHealthResult(
            healthy=True,
            message="Mock provider is operational",
        )

    async def search(
        self,
        query: str,
    ) -> list[ProviderSearchResult]:
        return [
            ProviderSearchResult(
                provider_id=self.id,
                external_id=f"mock:{query}",
                title=query,
            )
        ]

    async def resolve_movie(
        self,
        tmdb_id: int,
    ) -> list[PlaybackSource]:
        return [
            PlaybackSource(
                provider_id=self.id,
                url=(
                    "https://example.invalid/"
                    f"movie/{tmdb_id}/master.m3u8"
                ),
                protocol="hls",
                quality="1080p",
                audio_languages=["en"],
            )
        ]

    async def resolve_episode(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> list[PlaybackSource]:
        return [
            PlaybackSource(
                provider_id=self.id,
                url=(
                    "https://example.invalid/"
                    f"tv/{tmdb_id}/s{season}e{episode}/master.m3u8"
                ),
                protocol="hls",
                quality="1080p",
                audio_languages=["en"],
            )
        ]
