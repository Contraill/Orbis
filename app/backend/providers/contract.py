from abc import ABC, abstractmethod

from providers.schemas import (
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderSearchResult,
)


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class MediaProvider(ABC):
    id: str
    name: str
    default_enabled: bool = True
    default_priority: int = 100
    capabilities: ProviderCapabilities

    @abstractmethod
    async def health_check(self) -> ProviderHealthResult:
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str) -> list[ProviderSearchResult]:
        raise NotImplementedError

    @abstractmethod
    async def resolve_movie(
        self,
        tmdb_id: int,
    ) -> list[PlaybackSource]:
        raise NotImplementedError

    @abstractmethod
    async def resolve_episode(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> list[PlaybackSource]:
        raise NotImplementedError
