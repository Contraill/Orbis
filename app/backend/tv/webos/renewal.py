"""Verified LG Developer Mode renewal using the paired TV and private session token."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.getenv("ORBIS_WEBOS_CONFIG_DIR", "/config/tv/webos"))
DEVICES = ROOT / "devices.json"
ARES_HOME = ROOT / "ares-home"
TOKENS = ROOT / "tokens"
INTERVAL = timedelta(days=30)
RETRY = timedelta(days=1)
MIN_RENEWED = timedelta(days=30)
MIN_INCREASE = timedelta(hours=1)
_lock = threading.RLock()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read() -> dict[str, dict]:
    try:
        data = json.loads(DEVICES.read_text())
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def _save(devices: dict[str, dict]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ROOT, 0o700)
    temp = ROOT / "devices.json.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(devices, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, DEVICES)
    finally:
        temp.unlink(missing_ok=True)


def register(device_id: str, target: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", device_id):
        raise ValueError("Device ID must be the 32-character ID displayed on the TV")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", target):
        raise ValueError("Target must be a configured ares device name")
    with _lock:
        devices = _read()
        previous = devices.get(device_id, {})
        devices[device_id] = {
            "target": target,
            "registered_at": previous.get("registered_at", utcnow().isoformat()),
            "last_checkin": previous.get("last_checkin"),
            "last_attempt": previous.get("last_attempt"),
            "last_successful_renewal": previous.get("last_successful_renewal"),
            "status": previous.get("status", "registered"),
            "error": previous.get("error"),
        }
        _save(devices)


def record_checkin(device_id: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{32}", device_id):
        return False
    with _lock:
        devices = _read()
        if device_id not in devices:
            return False
        now = utcnow()
        last = _timestamp(devices[device_id].get("last_checkin"))
        if last and now - last < timedelta(minutes=15):
            return False
        devices[device_id]["last_checkin"] = now.isoformat()
        _save(devices)
        return True


def reset_after_manual_reenable(device_id: str) -> None:
    """Operator confirms Developer Mode was re-enabled on the physical TV."""
    with _lock:
        devices = _read()
        if device_id not in devices:
            raise ValueError("Unknown TV installation ID")
        devices[device_id]["status"] = "registered"
        devices[device_id]["last_attempt"] = None
        devices[device_id]["error"] = None
        _save(devices)


def _timestamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def is_due(device: dict, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if device.get("status") == "expired_manual_recovery_required":
        return False
    last_success = _timestamp(device.get("last_successful_renewal"))
    if last_success and now - last_success < INTERVAL:
        return False
    last_attempt = _timestamp(device.get("last_attempt"))
    return not last_attempt or now - last_attempt >= RETRY


def _ares_env() -> dict[str, str]:
    env = os.environ.copy()
    ARES_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    env["HOME"] = str(ARES_HOME)
    return env


def capture_session_token(device_id: str) -> None:
    """Read a paired TV's token directly into private storage, never stdout/logs."""
    device = _read().get(device_id)
    if not device:
        raise ValueError("Unknown TV installation ID")
    try:
        result = subprocess.run(
            ["ares-novacom", "--run", "cat /var/luna/preferences/devmode_enabled", "-d", device["target"]],
            env=_ares_env(), capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not read the paired TV session token") from exc
    token = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", token):
        raise RuntimeError("Paired TV did not provide a valid session token")
    TOKENS.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(TOKENS, 0o700)
    path = TOKENS / device_id
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(token)
    os.chmod(path, 0o600)


def _token(device_id: str) -> str | None:
    try:
        value = (TOKENS / device_id).read_text().strip()
    except FileNotFoundError:
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_-]{16,256}", value) else None


def _session_request(action: str, token: str) -> dict:
    # The token is never passed to a shell or included in an exception/status.
    url = f"https://developer.lge.com/secure/{action}.dev?" + urllib.parse.urlencode({"sessionToken": token})
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def _remaining(token: str) -> timedelta | None:
    try:
        data = _session_request("CheckDevModeSession", token)
        if data.get("result") != "success":
            return None
        parts = str(data.get("errorMsg", "")).split(":")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        hours, minutes, seconds = map(int, parts)
        if minutes > 59 or seconds > 59:
            return None
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _launch(target: str, command: str) -> str:
    args = (["ares-launch", "com.palmdts.devmode", "-p", "extend=true", "-d", target]
            if command == "current" else ["ares-extend-dev", "-d", target])
    try:
        result = subprocess.run(args, env=_ares_env(), capture_output=True, text=True, timeout=90, check=False)
        if result.returncode == 0:
            return "launched"
        output = (result.stdout + result.stderr).lower()
        if any(term in output for term in ("not installed", "not supported", "unsupported", "unknown command")):
            return "unsupported"
        return "unreachable"
    except (OSError, subprocess.TimeoutExpired):
        return "unreachable"


def _verified(before: timedelta, after: timedelta | None) -> bool:
    return after is not None and after >= MIN_RENEWED and after - before >= MIN_INCREASE


def _confirm_renewal(token: str, before: timedelta) -> tuple[bool, bool]:
    """Allow the TV/LG session service a few seconds to publish its new expiry."""
    for attempt in range(3):
        if attempt:
            time.sleep(2)
        after = _remaining(token)
        if after is None:
            return False, False
        if _verified(before, after):
            return True, True
    return False, True


def _renew(device_id: str, target: str) -> tuple[str, str | None]:
    token = _token(device_id)
    if not token:
        return "retry_pending", "session_token_not_paired"
    before = _remaining(token)
    if before is None:
        return "retry_pending", "session_check_unavailable"
    if before <= timedelta(0):
        return "expired_manual_recovery_required", "developer_mode_expired"

    # Current CLI first. Legacy CLI and token reset are compatibility fallbacks.
    for command, available in (("current", shutil.which("ares-launch")),
                               ("legacy", shutil.which("ares-extend-dev"))):
        if not available:
            continue
        outcome = _launch(target, command)
        if outcome == "unreachable":
            return "retry_pending", "device_offline_or_renewal_failed"
        if outcome == "launched":
            verified, queried = _confirm_renewal(token, before)
            if verified:
                return "ok", None
            if not queried:
                return "retry_pending", "renewal_verification_unavailable"

    # Some older TV/CLI combinations require LG's token reset endpoint.
    # HTTP success alone is never accepted as a successful renewal.
    try:
        response = _session_request("ResetDevModeSession", token)
        if response.get("result") == "success":
            verified, queried = _confirm_renewal(token, before)
            if verified:
                return "ok", None
            if not queried:
                return "retry_pending", "renewal_verification_unavailable"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return "retry_pending", "device_offline_or_renewal_unverified"


def run_due(device_id: str | None = None, now: datetime | None = None) -> int:
    now = now or utcnow()
    attempted = 0
    with _lock:
        devices = _read()
        for identity, device in devices.items():
            if device_id and identity != device_id:
                continue
            if not is_due(device, now):
                continue
            device["last_attempt"] = now.isoformat()
            device["status"] = "renewing"
            _save(devices)
            status, error = _renew(identity, device["target"])
            device["status"] = status
            device["error"] = error
            if status == "ok":
                device["last_successful_renewal"] = now.isoformat()
            _save(devices)
            attempted += 1
    return attempted


def local_status() -> list[dict]:
    """For host-side CLI only; no HTTP route exposes target or renewal state."""
    with _lock:
        return [{"device_id": key, **value} for key, value in _read().items()]
