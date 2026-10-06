"""Run with `docker compose exec backend python -m tv.webos ...`."""
import argparse
import json

from .renewal import capture_session_token, local_status, register, reset_after_manual_reenable, run_due


def main() -> None:
    parser = argparse.ArgumentParser(description="Orbis webOS Developer Mode maintenance")
    actions = parser.add_subparsers(dest="action", required=True)
    add = actions.add_parser("register", help="Associate TV installation ID with a paired ares target")
    add.add_argument("device_id")
    add.add_argument("target")
    actions.add_parser("status", help="Show private local renewal status")
    capture = actions.add_parser("capture-token", help="Store the paired TV session token privately")
    capture.add_argument("device_id")
    renew = actions.add_parser("renew", help="Run a due renewal now")
    renew.add_argument("device_id", nargs="?")
    reset = actions.add_parser("reset", help="After manually re-enabling Developer Mode")
    reset.add_argument("device_id")
    args = parser.parse_args()
    if args.action == "register":
        register(args.device_id, args.target)
        print("webOS TV registered; credentials remain in /config/tv/webos/ares-home")
    elif args.action == "status":
        print(json.dumps(local_status(), indent=2))
    elif args.action == "capture-token":
        capture_session_token(args.device_id)
        print("webOS session token stored privately")
    elif args.action == "renew":
        print(f"Renewal attempts: {run_due(args.device_id)}")
    elif args.action == "reset":
        reset_after_manual_reenable(args.device_id)
        print("Renewal state reset after manual TV recovery")


if __name__ == "__main__":
    main()
