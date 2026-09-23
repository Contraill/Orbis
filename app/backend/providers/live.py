import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from providers.registry import (
    LIVE_PROVIDER_ROOT,
    get_provider,
    registry_lock,
    reload_registry_if_live,
    reload_registry_if_factory,
    reload_registry,
    factory_code,
    provider_sources,
)


PROVIDER_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]{1,63}$"
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_RESULT_PREFIX = "__MEDIA_APP_PROVIDER__"
VALIDATION_TIMEOUT_SECONDS = 8
VALIDATION_OUTPUT_LIMIT = 1_000_000


class LiveProviderError(RuntimeError):
    pass


class LiveProviderNotFound(LiveProviderError):
    pass


class LiveProviderConflict(LiveProviderError):
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
        raise LiveProviderConflict(
            "Provider directory already exists"
        )

    if get_provider(provider_id) is not None:
        raise LiveProviderConflict(
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

    settings_path = directory / "settings.json"
    settings_path.write_text(
        "{}\n",
        encoding="utf-8",
    )
    os.chmod(settings_path, 0o600)

    return provider_editor_state(provider_id)


def create_factory_override(provider_id: str) -> dict:
    directory = provider_dir(provider_id)
    with registry_lock():
        code = factory_code(provider_id)
        if code is None:
            raise LiveProviderNotFound("Factory provider not found")
        if directory.exists():
            if not (directory / "factory-override").is_file():
                raise LiveProviderConflict("Provider directory is not a factory override")
            return provider_editor_state(provider_id)
        directory.mkdir(parents=True)
        (directory / "versions").mkdir()
        _atomic_write_text(code, directory / "draft.py")
        _atomic_write_text("{}\n", directory / "settings.json")
        os.chmod(directory / "settings.json", 0o600)
        _atomic_write_text(provider_id, directory / "factory-override")
    return provider_editor_state(provider_id)


def revert_to_factory(provider_id: str) -> dict:
    directory = provider_dir(provider_id)
    with registry_lock():
        if factory_code(provider_id) is None or not (directory / "factory-override").is_file():
            raise LiveProviderNotFound("Factory override not found")
        active = directory / "active.py"
        previous = active.read_bytes() if active.is_file() else None
        if previous is not None:
            (directory / "versions").mkdir(exist_ok=True)
            shutil.copy2(active, directory / "versions" / _version_name())
            active.unlink()
        try:
            if not reload_registry_if_factory(provider_id):
                raise LiveProviderError("Factory provider failed to load")
        except Exception:
            _restore_active(active, previous)
            raise
    return provider_editor_state(provider_id)


def delete_live_provider(provider_id: str) -> None:
    """Remove only a user-created adapter; factory code is never deletable."""
    directory = provider_dir(provider_id)
    with registry_lock():
        if not directory.is_dir() or directory.is_symlink():
            raise LiveProviderNotFound("Live provider not found")
        if factory_code(provider_id) is not None or (directory / "factory-override").exists():
            raise LiveProviderConflict("Factory providers cannot be deleted; revert to factory instead")

        # Move out of the discovery root before reloading, restoring on failure.
        staging = Path(tempfile.mkdtemp(prefix="orbis-provider-delete-", dir=LIVE_PROVIDER_ROOT.parent))
        staged = staging / provider_id
        try:
            os.replace(directory, staged)
            try:
                reload_registry()
            except Exception:
                os.replace(staged, directory)
                raise
            shutil.rmtree(staging)
        finally:
            if staging.exists() and not staged.exists():
                staging.rmdir()


def save_draft(
    provider_id: str,
    code: str,
) -> dict:
    directory = provider_dir(provider_id)

    if not directory.exists():
        raise LiveProviderNotFound(
            "Live provider not found"
        )

    with registry_lock():
        _atomic_write_text(
            code,
            directory / "draft.py",
        )

    return provider_editor_state(provider_id)


def _validator_script() -> str:
    return r'''
import json
import resource
import sys
import types

from providers.contract import MediaProvider


path = sys.argv[1]
expected_id = sys.argv[2]
output_limit = int(sys.argv[3])
resource.setrlimit(
    resource.RLIMIT_FSIZE,
    (output_limit, output_limit),
)
module_name = "_provider_validation"
module = types.ModuleType(module_name)
module.__file__ = path
sys.modules[module_name] = module

with open(path, encoding="utf-8") as provider_file:
    source = provider_file.read()

exec(compile(source, path, "exec"), module.__dict__)

provider = getattr(module, "PROVIDER", None)

if not isinstance(provider, MediaProvider):
    raise TypeError(
        "PROVIDER must be a MediaProvider instance"
    )

if provider.id != expected_id:
    raise ValueError(
        "PROVIDER.id must match provider directory"
    )

print("__MEDIA_APP_PROVIDER__" + json.dumps({
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

    env = {
        key: value
        for key, value in os.environ.items()
        if key in {
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "PYTHONIOENCODING",
            "PYTHONUNBUFFERED",
        }
    }

    env["PYTHONPATH"] = str(BACKEND_ROOT)

    command = [
        sys.executable,
        "-c",
        _validator_script(),
        str(draft),
        provider_id,
        str(VALIDATION_OUTPUT_LIMIT),
    ]

    with tempfile.TemporaryFile(mode="w+") as stdout_file, \
         tempfile.TemporaryFile(mode="w+") as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
            env=env,
            cwd=BACKEND_ROOT,
        )

        try:
            process.wait(
                timeout=VALIDATION_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            errors.append(
                "Provider validation timed out"
            )
            return {
                "valid": False,
                "errors": errors,
                "provider": None,
            }

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(
            VALIDATION_OUTPUT_LIMIT + 1
        )
        stderr = stderr_file.read(
            VALIDATION_OUTPUT_LIMIT + 1
        )

    if (
        len(stdout) > VALIDATION_OUTPUT_LIMIT
        or len(stderr) > VALIDATION_OUTPUT_LIMIT
    ):
        return {
            "valid": False,
            "errors": [
                "Provider validation output exceeded the limit"
            ],
            "provider": None,
        }

    if process.returncode != 0:
        message = (
            stderr.strip()
            or stdout.strip()
            or "Provider import failed"
        )

        errors.append(message)

        return {
            "valid": False,
            "errors": errors,
            "provider": None,
        }

    output_line = next(
        (
            line.removeprefix(
                VALIDATION_RESULT_PREFIX
            )
            for line in reversed(
                stdout.splitlines()
            )
            if line.startswith(
                VALIDATION_RESULT_PREFIX
            )
        ),
        "",
    )

    try:
        provider_data = json.loads(output_line)
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


def _atomic_write_text(
    content: str,
    destination: Path,
) -> None:
    temporary = destination.with_name(
        f".{destination.name}.tmp"
    )
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, destination)


def _restore_active(
    active: Path,
    previous: bytes | None,
) -> None:
    if previous is None:
        active.unlink(missing_ok=True)
        return

    temporary = active.with_name(".active.rollback")
    temporary.write_bytes(previous)
    os.replace(temporary, active)


def activate_draft(provider_id: str) -> dict:
    directory = provider_dir(provider_id)
    draft = directory / "draft.py"
    active = directory / "active.py"
    versions = directory / "versions"

    with registry_lock():
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

        _atomic_copy(draft, active)
        loaded, errors = reload_registry_if_live(
            provider_id
        )

        if not loaded:
            _restore_active(active, previous)
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
        raise LiveProviderNotFound(
            "Version not found"
        )

    with registry_lock():
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

        _atomic_copy(selected, active)
        loaded, _ = reload_registry_if_live(
            provider_id
        )

        if not loaded:
            _restore_active(active, current)
            raise LiveProviderError(
                "Rollback version failed to load"
            )

        _atomic_copy(
            active,
            directory / "draft.py",
        )

    return provider_editor_state(provider_id)


def provider_editor_state(
    provider_id: str,
) -> dict:
    directory = provider_dir(provider_id)

    if not directory.exists():
        raise LiveProviderNotFound(
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
        "is_factory_override": (directory / "factory-override").is_file(),
        "implementation": provider_sources().get(provider_id),
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
    directory = provider_dir(provider_id)

    if not directory.exists():
        raise LiveProviderNotFound(
            "Live provider not found"
        )

    path = directory / "settings.json"

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
        raise LiveProviderNotFound(
            "Live provider not found"
        )

    path = directory / "settings.json"
    temporary = directory / ".settings.tmp"

    with registry_lock():
        temporary.write_text(
            json.dumps(
                settings,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    return settings
