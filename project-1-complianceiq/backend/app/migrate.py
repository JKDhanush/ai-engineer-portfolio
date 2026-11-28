"""Apply db/migrations/*.sql in order. Each file is idempotent (CREATE ... IF NOT EXISTS), so running them on
every start is safe and keeps existing databases (created before a table existed) up to date.
A real team would use Alembic/Flyway with a version table; for two migrations this stays simple."""

from pathlib import Path

import asyncpg

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


async def migrate(conn: asyncpg.Connection) -> list[str]:
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        await conn.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied
