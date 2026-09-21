import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from providers.registry import (
    LIVE_PROVIDER_ROOT,
    discovery_errors,
    get_provider,
    reload_registry,
)


PROVIDER_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]{1,63}$"
)


class LiveProviderError(RuntimeError):
    pass


class LiveProviderValidationError(LiveProviderError):
    def __init__(self, errors: list[str]):
        super().__init__("Provider validation failed")
        self.errors = errors


def validate_provider_id(provider_id: str) -> str:
    if not PROVIDER_ID_RE.fullmatch(provider_id):
        raise LiveProviderError(
            "Provider id must contain only lowercase "
            "letters, numbers, '-' or '_'"
        )

    return provider_id


def provider_dir(provider_id: str) -> Path:
    validate_provider_id(provider_id)

    return LIVE_PROVIDER_ROOT / provider_id


def template_code(
    provider_id: str,
    name: str,
) -> str:
    return f'''from providers.contract import MediaProvider
from providers.schemas import (
    AudioTrack,
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderSearchResult,
    SubtitleTrack,
)


class LiveProvider(MediaProvider):
    id = "{provider_id}"
    name = {name!r}

    default_enabled = False
    default_priority = 100

    capabilities = ProviderCapabilities(
        movie=True,
        episode=True,
        protocols=["hls"],
        selectable_audio=True,
        selectable_subtitles=True,
        burned_in_subtitles=False,
    )

    async def health_check(self) -> ProviderHealthResult:
        return ProviderHealthResult(
            healthy=True,
            message="Provider loaded",
        )

    async def search(
        self,
        query: str,
    ) -> list[ProviderSearchResult]:
        return []

    async def resolve_movie(
        self,
        tmdb_id: int,
    ) -> list[PlaybackSource]:
        return []

    async def resolve_episode(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> list[PlaybackSource]:
        return []


PROVIDER = LiveProvider()
'''


def create_live_provider(
    provider_id: str,
    name: str,
) -> dict:
    directory = provider_dir(provider_id)

    if directory.exists():
        raise LiveProviderError(
            "Provider directory already exists"
        )

    if get_provider(provider_id) is not None:
        raise LiveProviderError(
            "Provider id already exists"
        )

    directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    (directory / "versions").mkdir()
    (directory / "draft.py").write_text(
        template_code(provider_id, name),
        encoding="utf-8",
    )

    (directory / "settings.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    return provider_editor_state(provider_id)


def save_draft(
    provider_id: str,
    code: str,
) -> dict:
    directory = provider_dir(provider_id)

    if not directory.exists():
        raise LiveProviderError(
            "Live provider not found"
        )

    (directory / "draft.py").write_text(
        code,
        encoding="utf-8",
    )

    return provider_editor_state(provider_id)


def _validator_script() -> str:
    return r'''
import importlib.util
import json
import sys

from providers.contract import MediaProvider


path = sys.argv[1]
expected_id = sys.argv[2]

spec = importlib.util.spec_from_file_location(
    "_provider_validation",
    path,
)

if spec is None or spec.loader is None:
    raise RuntimeError("Cannot create module spec")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

provider = getattr(module, "PROVIDER", None)

if not isinstance(provider, MediaProvider):
    raise TypeError(
        "PROVIDER must be a MediaProvider instance"
    )

if provider.id != expected_id:
    raise ValueError(
        "PROVIDER.id must match provider directory"
    )

print(json.dumps({
    "provider_id": provider.id,
    "name": provider.name,
    "capabilities": provider.capabilities.model_dump(
        mode="json"
    ),
}))
'''


def validate_draft(provider_id: str) -> dict:
    directory = provider_dir(provider_id)
    draft = directory / "draft.py"

    if not draft.is_file():
        raise LiveProviderError(
            "Draft does not exist"
        )

    code = draft.read_text(encoding="utf-8")
    errors: list[str] = []

    try:
        compile(
            code,
            str(draft),
            "exec",
        )
    except SyntaxError as exc:
        errors.append(
            f"SyntaxError line {exc.lineno}: "
            f"{exc.msg}"
        )

        return {
            "valid": False,
            "errors": errors,
            "provider": None,
        }

    env = os.environ.copy()

    current_pythonpath = env.get(
        "PYTHONPATH",
        "",
    )

    env["PYTHONPATH"] = (
        f"/app:{current_pythonpath}"
        if current_pythonpath
        else "/app"
    )

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _validator_script(),
                str(draft),
                provider_id,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            env=env,
            cwd="/app",
        )

    except subprocess.TimeoutExpired:
        errors.append(
            "Provider validation timed out"
        )

        return {
            "valid": False,
            "errors": errors,
            "provider": None,
        }

    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Provider import failed"
        )

        errors.append(message)

        return {
            "valid": False,
            "errors": errors,
            "provider": None,
        }

    try:
        provider_data = json.loads(
            result.stdout.strip()
        )
    except json.JSONDecodeError:
        errors.append(
            "Validator returned invalid output"
        )

        return {
            "valid": False,
            "errors": errors,
            "provider": None,
        }

    return {
        "valid": True,
        "errors": [],
        "provider": provider_data,
    }


def _version_name() -> str:
    now = datetime.now(timezone.utc)

    return now.strftime(
        "%Y%m%dT%H%M%S_%fZ.py"
    )


def _atomic_copy(
    source: Path,
    destination: Path,
) -> None:
    temporary = destination.with_name(
        f".{destination.name}.tmp"
    )

    shutil.copy2(
        source,
        temporary,
    )

    os.replace(
        temporary,
        destination,
    )


def activate_draft(provider_id: str) -> dict:
    directory = provider_dir(provider_id)
    draft = directory / "draft.py"
    active = directory / "active.py"
    versions = directory / "versions"

    validation = validate_draft(provider_id)

    if not validation["valid"]:
        raise LiveProviderValidationError(
            validation["errors"]
        )

    previous = (
        active.read_bytes()
        if active.exists()
        else None
    )

    if active.exists():
        versions.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            active,
            versions / _version_name(),
        )

    _atomic_copy(
        draft,
        active,
    )

    reload_registry()

    loaded = get_provider(provider_id)
    errors = discovery_errors()

    if loaded is None:
        if previous is None:
            active.unlink(missing_ok=True)
        else:
            temporary = active.with_name(
                ".active.rollback"
            )

            temporary.write_bytes(previous)

            os.replace(
                temporary,
                active,
            )

        reload_registry()

        relevant = errors.get(
            f"live:{provider_id}",
            "Provider failed to activate",
        )

        raise LiveProviderValidationError(
            [relevant]
        )

    return provider_editor_state(provider_id)


def list_versions(
    provider_id: str,
) -> list[str]:
    versions = (
        provider_dir(provider_id)
        / "versions"
    )

    if not versions.exists():
        return []

    return sorted(
        (
            path.name
            for path in versions.glob("*.py")
            if path.is_file()
        ),
        reverse=True,
    )


def rollback_provider(
    provider_id: str,
    version: str,
) -> dict:
    directory = provider_dir(provider_id)
    versions = directory / "versions"
    active = directory / "active.py"

    version_name = Path(version).name

    if version_name != version:
        raise LiveProviderError(
            "Invalid version name"
        )

    selected = versions / version_name

    if not selected.is_file():
        raise LiveProviderError(
            "Version not found"
        )

    current = (
        active.read_bytes()
        if active.exists()
        else None
    )

    if active.exists():
        shutil.copy2(
            active,
            versions / _version_name(),
        )

    _atomic_copy(
        selected,
        active,
    )

    reload_registry()

    if get_provider(provider_id) is None:
        if current is not None:
            temporary = active.with_name(
                ".active.rollback"
            )

            temporary.write_bytes(current)

            os.replace(
                temporary,
                active,
            )

        reload_registry()

        raise LiveProviderError(
            "Rollback version failed to load"
        )

    shutil.copy2(
        active,
        directory / "draft.py",
    )

    return provider_editor_state(provider_id)


def provider_editor_state(
    provider_id: str,
) -> dict:
    directory = provider_dir(provider_id)

    if not directory.exists():
        raise LiveProviderError(
            "Live provider not found"
        )

    draft = directory / "draft.py"
    active = directory / "active.py"

    provider = get_provider(provider_id)

    return {
        "provider_id": provider_id,
        "name": (
            provider.name
            if provider is not None
            else provider_id
        ),
        "loaded": provider is not None,
        "has_active": active.is_file(),
        "draft_code": (
            draft.read_text(encoding="utf-8")
            if draft.is_file()
            else ""
        ),
        "active_code": (
            active.read_text(encoding="utf-8")
            if active.is_file()
            else None
        ),
        "versions": list_versions(
            provider_id
        ),
    }


def list_live_providers() -> list[dict]:
    LIVE_PROVIDER_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = []

    for directory in sorted(
        LIVE_PROVIDER_ROOT.iterdir()
    ):
        if not directory.is_dir():
            continue

        try:
            result.append(
                provider_editor_state(
                    directory.name
                )
            )
        except LiveProviderError:
            continue

    return result


def get_settings(
    provider_id: str,
) -> dict:
    path = (
        provider_dir(provider_id)
        / "settings.json"
    )

    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        raise LiveProviderError(
            "settings.json is invalid"
        ) from exc

    if not isinstance(data, dict):
        raise LiveProviderError(
            "Provider settings must be an object"
        )

    return data


def save_settings(
    provider_id: str,
    settings: dict,
) -> dict:
    directory = provider_dir(provider_id)

    if not directory.exists():
        raise LiveProviderError(
            "Live provider not found"
        )

    path = directory / "settings.json"
    temporary = directory / ".settings.tmp"

    temporary.write_text(
        json.dumps(
            settings,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        path,
    )

    return settings
