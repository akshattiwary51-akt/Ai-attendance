"""Create the first administrator.

    SUPABASE_URL=... SUPABASE_ANON_KEY=... SUPABASE_SERVICE_ROLE_KEY=... python scripts/create_admin.py admin@college.edu

The password is read from the ADMIN_PASSWORD env var or prompted (never passed on the command line).
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import auth_service  # noqa: E402
from src.utils.errors import AppError  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password (min 8 chars): ")
    try:
        auth_service.create_admin(argv[1], password)
    except AppError as exc:
        print(f"Failed: {exc.user_message}")
        return 1
    print(f"Administrator {argv[1].lower()} created. Log in via 'Administrator login' on the home page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
