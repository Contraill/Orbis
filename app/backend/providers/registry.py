from providers.adapters.mock_broken.provider import MockBrokenProvider
from providers.adapters.mock_stream.provider import MockStreamProvider
from providers.contract import MediaProvider


_PROVIDERS: dict[str, MediaProvider] = {
    provider.id: provider
    for provider in (
        MockBrokenProvider(),
        MockStreamProvider(),
    )
}


def all_providers() -> dict[str, MediaProvider]:
    return dict(_PROVIDERS)


def get_provider(provider_id: str) -> MediaProvider | None:
    return _PROVIDERS.get(provider_id)
