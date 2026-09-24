from providers.contract import MediaProvider, ProviderUnavailable
from providers.schemas import (
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderSearchResult,
)


class MockBrokenProvider(MediaProvider):
    id = "mock-broken"
    name = "Mock Broken"
    default_enabled = False
    default_priority = 10

    capabilities = ProviderCapabilities(
        movie=True,
        episode=True,
        protocols=["hls"],
    )

    async def health_check(self) -> ProviderHealthResult:
        return ProviderHealthResult(
            healthy=False,
            message="Intentional mock failure",
        )

    async def search(
        self,
        query: str,
    ) -> list[ProviderSearchResult]:
        raise ProviderUnavailable("Intentional mock failure")

    async def resolve_movie(
        self,
        tmdb_id: int,
    ) -> list[PlaybackSource]:
        raise ProviderUnavailable("Intentional mock failure")

    async def resolve_episode(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> list[PlaybackSource]:
        raise ProviderUnavailable("Intentional mock failure")


PROVIDER = MockBrokenProvider()
