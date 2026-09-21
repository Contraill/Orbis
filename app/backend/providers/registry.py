import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path

from providers import adapters
from providers.contract import MediaProvider


LIVE_PROVIDER_ROOT = Path("/config/providers")

_PROVIDERS: dict[str, MediaProvider] | None = None
_DISCOVERY_ERRORS: dict[str, str] = {}
_PROVIDER_SOURCES: dict[str, str] = {}


def _load_provider_module(
    module_name: str,
    path: Path,
) -> MediaProvider:
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    provider = getattr(module, "PROVIDER", None)

    if not isinstance(provider, MediaProvider):
        raise TypeError(
            "provider.py must export PROVIDER "
            "as a MediaProvider instance"
        )

    if not provider.id:
        raise ValueError("Provider id cannot be empty")

    return provider


def _discover_builtin(
    discovered: dict[str, MediaProvider],
    sources: dict[str, str],
    errors: dict[str, str],
) -> None:
    for module_info in pkgutil.iter_modules(adapters.__path__):
        if not module_info.ispkg:
            continue

        adapter_name = module_info.name

        if adapter_name.startswith("_"):
            continue

        module_name = (
            f"{adapters.__name__}.{adapter_name}.provider"
        )

        try:
            module = importlib.import_module(module_name)
            provider = getattr(module, "PROVIDER", None)

            if not isinstance(provider, MediaProvider):
                raise TypeError(
                    "provider.py must export PROVIDER "
                    "as a MediaProvider instance"
                )

            if provider.id in discovered:
                raise ValueError(
                    f"Duplicate provider id: {provider.id}"
                )

            discovered[provider.id] = provider
            sources[provider.id] = "builtin"

        except Exception as exc:
            errors[f"builtin:{adapter_name}"] = (
                f"{type(exc).__name__}: {exc}"
            )


def _discover_live(
    discovered: dict[str, MediaProvider],
    sources: dict[str, str],
    errors: dict[str, str],
) -> None:
    LIVE_PROVIDER_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    for directory in sorted(LIVE_PROVIDER_ROOT.iterdir()):
        if not directory.is_dir():
            continue

        provider_id = directory.name
        active_path = directory / "active.py"

        if not active_path.is_file():
            continue

        try:
            module_name = (
                "_media_app_live_"
                f"{provider_id}_"
                f"{active_path.stat().st_mtime_ns}"
            )

            provider = _load_provider_module(
                module_name,
                active_path,
            )

            if provider.id != provider_id:
                raise ValueError(
                    "Provider id must match its directory: "
                    f"{provider_id}"
                )

            if provider.id in discovered:
                raise ValueError(
                    f"Provider id conflicts with "
                    f"an existing provider: {provider.id}"
                )

            discovered[provider.id] = provider
            sources[provider.id] = "live"

        except Exception as exc:
            errors[f"live:{provider_id}"] = (
                f"{type(exc).__name__}: {exc}"
            )


def reload_registry() -> dict[str, MediaProvider]:
    global _PROVIDERS
    global _DISCOVERY_ERRORS
    global _PROVIDER_SOURCES

    discovered: dict[str, MediaProvider] = {}
    sources: dict[str, str] = {}
    errors: dict[str, str] = {}

    _discover_builtin(
        discovered,
        sources,
        errors,
    )

    _discover_live(
        discovered,
        sources,
        errors,
    )

    _PROVIDERS = discovered
    _DISCOVERY_ERRORS = errors
    _PROVIDER_SOURCES = sources

    return dict(discovered)


def all_providers() -> dict[str, MediaProvider]:
    global _PROVIDERS

    if _PROVIDERS is None:
        reload_registry()

    return dict(_PROVIDERS or {})


def get_provider(
    provider_id: str,
) -> MediaProvider | None:
    return all_providers().get(provider_id)


def discovery_errors() -> dict[str, str]:
    if _PROVIDERS is None:
        reload_registry()

    return dict(_DISCOVERY_ERRORS)


def provider_sources() -> dict[str, str]:
    if _PROVIDERS is None:
        reload_registry()

    return dict(_PROVIDER_SOURCES)
