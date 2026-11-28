"""Create (or update) a user. Run from backend/ with the venv active and the database up:
    python scripts/create_user.py analyst@example.com --role analyst
    python scripts/create_user.py admin@example.com --role admin --access public,internal
The password is asked for interactively, so it never ends up in your shell history.
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.migrate import migrate  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("--role", choices=["analyst", "admin"], default="analyst")
    ap.add_argument("--access", default="public", help="comma-separated document access levels")
    ap.add_argument("--entity", help="default entity filter, e.g. nbfcs")
    args = ap.parse_args()
    password = getpass.getpass("Password (min 8 chars): ")
    if len(password) < 8:
        raise SystemExit("password too short")
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        await migrate(conn)
        await conn.execute(
            """INSERT INTO users (email, password_hash, role, access_levels, entity_type) VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role,
               access_levels = EXCLUDED.access_levels, entity_type = EXCLUDED.entity_type""",
            args.email.lower(), hash_password(password), args.role, args.access.split(","), args.entity)
    finally:
        await conn.close()
    print(f"user {args.email} ready ({args.role}, access: {args.access})")


if __name__ == "__main__":
    asyncio.run(main())
