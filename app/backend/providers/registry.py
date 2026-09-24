import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from threading import RLock
from types import ModuleType

from providers import adapters
from providers.contract import MediaProvider
from core.errors import safe_text


LIVE_PROVIDER_ROOT = Path("/config/providers")

_PROVIDERS: dict[str, MediaProvider] | None = None
_DISCOVERY_ERRORS: dict[str, str] = {}
_REGISTRY_LOCK = RLock()
_PROVIDER_SOURCES: dict[str, str] = {}


def _load_provider_module(
    module_name: str,
    path: Path,
) -> MediaProvider:
    module = ModuleType(module_name)
    module.__file__ = str(path)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module

    try:
        source = path.read_text(encoding="utf-8")
        code = compile(source, str(path), "exec")
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous
        raise

    provider = getattr(module, "PROVIDER", None)

    if not isinstance(provider, MediaProvider):
        raise TypeError(
            "provider.py must export PROVIDER "
            "as a MediaProvider instance"
        )

    if not provider.id:
        raise ValueError("Provider id cannot be empty")

    from providers.settings import definitions
    definitions(provider)

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

            from providers.settings import definitions
            definitions(provider)

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
        if directory.is_symlink() or active_path.is_symlink():
            errors[f"live:{provider_id}"] = "Provider symlinks are not allowed"
            continue

        if not active_path.is_file():
            continue

        try:
            module_name = (
                "_media_app_live_"
                f"{provider_id}"
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

            if provider.id in discovered and not (
                sources.get(provider.id) == "builtin"
                and (directory / "factory-override").is_file()
            ):
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


def registry_lock() -> RLock:
    return _REGISTRY_LOCK


def factory_code(provider_id: str) -> str | None:
    """Read the shipped adapter, never the currently installed override."""
    providers, sources, errors = {}, {}, {}
    _discover_builtin(providers, sources, errors)
    provider = providers.get(provider_id)
    if provider is None:
        return None
    module = importlib.import_module(type(provider).__module__)
    return inspect.getsource(module)


def reload_registry_if_factory(provider_id: str) -> bool:
    with _REGISTRY_LOCK:
        discovered, sources, errors = _discover_registry()
        if sources.get(provider_id) != "builtin":
            return False
        _install_registry(discovered, sources, errors)
        return True


def _discover_registry() -> tuple[
    dict[str, MediaProvider],
    dict[str, str],
    dict[str, str],
]:
    discovered: dict[str, MediaProvider] = {}
    sources: dict[str, str] = {}
    errors: dict[str, str] = {}

    _discover_builtin(discovered, sources, errors)
    _discover_live(discovered, sources, errors)

    return discovered, sources, errors


def _install_registry(
    discovered: dict[str, MediaProvider],
    sources: dict[str, str],
    errors: dict[str, str],
) -> None:
    global _PROVIDERS
    global _DISCOVERY_ERRORS
    global _PROVIDER_SOURCES

    _PROVIDERS = discovered
    _DISCOVERY_ERRORS = errors
    _PROVIDER_SOURCES = sources
    live_modules = {f"_media_app_live_{key}" for key, kind in sources.items() if kind == "live"}
    for name in list(sys.modules):
        if name.startswith("_media_app_live_") and name not in live_modules:
            sys.modules.pop(name, None)


def reload_registry() -> dict[str, MediaProvider]:
    with _REGISTRY_LOCK:
        discovered, sources, errors = _discover_registry()
        _install_registry(discovered, sources, errors)
        return dict(discovered)


def reload_registry_if_live(
    provider_id: str,
) -> tuple[bool, dict[str, str]]:
    """Install a registry only when its live provider loaded."""
    with _REGISTRY_LOCK:
        discovered, sources, errors = _discover_registry()

        if sources.get(provider_id) != "live":
            return False, errors

        _install_registry(discovered, sources, errors)
        return True, errors


def all_providers() -> dict[str, MediaProvider]:
    global _PROVIDERS

    with _REGISTRY_LOCK:
        if _PROVIDERS is None:
            reload_registry()

        return dict(_PROVIDERS or {})


def get_provider(
    provider_id: str,
) -> MediaProvider | None:
    return all_providers().get(provider_id)


def discovery_errors() -> dict[str, str]:
    with _REGISTRY_LOCK:
        if _PROVIDERS is None:
            reload_registry()

        return {key:safe_text(value) for key,value in _DISCOVERY_ERRORS.items()}


def provider_sources() -> dict[str, str]:
    with _REGISTRY_LOCK:
        if _PROVIDERS is None:
            reload_registry()

        return dict(_PROVIDER_SOURCES)
