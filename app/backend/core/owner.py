"""Local-console credential setup/recovery: python -m core.owner (interactive TTY)."""
from getpass import getpass

from sqlalchemy import delete
from core.auth import hash_password
from db.models.foundation import Installation, AdminSession
from db.session import SessionLocal


def main():
    password = getpass("New Orbis owner password (12-128 characters): ")
    if not 12 <= len(password) <= 128 or password != getpass("Confirm password: "):
        raise SystemExit("Password length or confirmation invalid; nothing changed")
    with SessionLocal() as db:
        config = db.get(Installation, 1)
        if not config or config.owner_id is None:
            raise SystemExit("Use the first-run web setup to create the owner first")
        config.password_hash = hash_password(password)
        config.failed_logins = 0
        config.locked_until = None
        db.execute(delete(AdminSession))
        db.commit()
    print("Owner password updated; all previous admin sessions revoked.")


if __name__ == "__main__":
    main()
