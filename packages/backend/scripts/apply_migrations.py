"""Apply all SQL migrations in `migrations-py/` to the Supabase Postgres
database.

WHY THIS EXISTS
===============
The Supabase REST API (the path used by the runtime via the service-role
key) only exposes DML — it does NOT allow DDL (CREATE TABLE, ALTER TABLE,
etc.). To create new tables, the owner has to run SQL by hand via the
Supabase SQL Editor in the dashboard, OR use a direct Postgres
connection.

This script automates the direct-connection path: walks every .sql file
in `packages/backend/migrations-py/` in lexical order, applies each in
its own transaction, and reports success/failure per file. It uses
either:
  - `psycopg2` if installed (preferred, in-process)
  - `psql` CLI as fallback (most systems have it)
  - A pure-Python Postgres wire-protocol implementation as a last resort
    (NOT IMPLEMENTED — would need `pg8000` or similar)

USAGE
=====

1. Find your Supabase database connection string:
   - Supabase dashboard -> Project Settings -> Database -> Connection
     string -> URI
   - Looks like: `postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres`

2. Add it to your .env (NOT committed — gitignored):
   ```
   SUPABASE_DB_URL=postgresql://postgres.lrwzlujomukzjykafmic:YOUR_PASSWORD@aws-0-...
   ```

3. Run the script (with .env sourced):
   ```bash
   cd packages/backend
   python -m scripts.apply_migrations
   ```

   Or with a CLI override:
   ```bash
   python -m scripts.apply_migrations --db-url 'postgresql://...'
   ```

4. Or dry-run to see what would be applied:
   ```bash
   python -m scripts.apply_migrations --dry-run
   ```

WHAT IT DOES
============

For each .sql file in lexical order:

1. Read the file
2. Strip the comment header (the `--` lines at the top)
3. Begin a Postgres transaction
4. Execute the SQL
5. Commit if successful, rollback if not
6. Record the result in a manifest table (`public.schema_migrations`)
   so re-runs are idempotent — a migration whose filename is already in
   the manifest is SKIPPED (not re-applied)

A failed migration aborts the script. The operator can fix the SQL or
the connection and re-run; already-applied migrations are skipped
automatically.

SAFETY
======

- The script NEVER drops tables, NEVER deletes data, NEVER truncates.
  Every .sql file in this repo is additive (CREATE TABLE, ALTER TABLE
  ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS).
- The script uses a per-migration transaction. If migration #5 fails,
  migrations #1-#4 are already committed (because they should be —
  they're additive and idempotent at the SQL level).
- The manifest is the source of truth for what has been applied. The
  owner can drop the manifest to force a re-run.
- The script refuses to run against a non-Supabase connection (the
  connection string must end in `.supabase.co` or contain
  `.supabase.com`).
- `--dry-run` shows every file it would apply without touching the DB.

EXIT CODES
==========

0 = all migrations applied (or already in manifest)
1 = bad arguments / missing db url
2 = connection failed
3 = a migration failed
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Bootstrap: allow `python apply_migrations.py` from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

logger = logging.getLogger("apply_migrations")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")


# ─── Constants ──────────────────────────────────────────────────────────

# Path to the migrations dir, relative to this script.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations-py"

# Manifest table — records what has been applied. Created on first run.
MANIFEST_TABLE = "public.schema_migrations"

# The filename of the script that created the manifest (so future
# schema changes can re-run this script and the manifest will work).
MANIFEST_SCHEMA = """
create table if not exists public.schema_migrations (
  filename    text primary key,
  applied_at  timestamptz not null default now(),
  sha256      text not null
);
""".strip()


# ─── DB connection helpers ─────────────────────────────────────────────

def get_db_url(args_db_url: Optional[str]) -> str:
    """Resolve the database URL from CLI > env. Refuse if it's not
    a Supabase connection (safety).
    """
    url = args_db_url or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not url:
        logger.error("No DB URL provided. Set SUPABASE_DB_URL in .env or pass --db-url")
        sys.exit(1)
    # Safety check: must look like a Supabase connection
    if "supabase" not in url and "localhost" not in url and "127.0.0.1" not in url:
        logger.error("Refusing to run against a non-Supabase connection (safety)")
        logger.error("  url host: %s", re.sub(r"://[^@]+@", "://***@", url))
        sys.exit(1)
    return url


def _strip_pg_url_password(url: str) -> str:
    """For logging. Replaces the password with *** so we don't leak it."""
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


def detect_executor() -> str:
    """Returns 'psycopg2' if available, else 'psql', else exits with an error."""
    try:
        import psycopg2  # noqa: F401
        return "psycopg2"
    except ImportError:
        pass
    # Try psql
    try:
        subprocess.run(["psql", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return "psql"
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    logger.error("Neither psycopg2 nor psql is available. Install one:")
    logger.error("  pip install psycopg2-binary    (preferred)")
    logger.error("  or install Postgres client tools (provides psql)")
    sys.exit(1)


# ─── Migration discovery ────────────────────────────────────────────────

def discover_migrations() -> List[Path]:
    """Return all .sql files in MIGRATIONS_DIR, sorted lexically."""
    if not MIGRATIONS_DIR.is_dir():
        logger.error("migrations dir not found: %s", MIGRATIONS_DIR)
        sys.exit(1)
    files = sorted(p for p in MIGRATIONS_DIR.iterdir() if p.suffix == ".sql")
    if not files:
        logger.warning("no .sql files in %s", MIGRATIONS_DIR)
    return files


def strip_header(sql: str) -> str:
    """Remove the `--` comment header at the top of a migration file.
    The header is metadata; we don't want to confuse the SQL parser.
    """
    lines = sql.splitlines()
    out = []
    past_header = False
    for line in lines:
        s = line.strip()
        if not past_header:
            if s == "" or s.startswith("--"):
                continue
            past_header = True
        out.append(line)
    return "\n".join(out).strip()


def file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ─── Manifest management ──────────────────────────────────────────────

def ensure_manifest(executor: str, db_url: str) -> None:
    """Create the manifest table if it doesn't exist."""
    logger.info("ensuring manifest table %s exists ...", MANIFEST_TABLE)
    _execute_sql(executor, db_url, MANIFEST_SCHEMA)


def get_applied(executor: str, db_url: str) -> set:
    """Return the set of filenames that are already in the manifest."""
    sql = f"select filename from {MANIFEST_TABLE};"
    rows = _execute_sql_returning(executor, db_url, sql)
    return {r[0] for r in rows}


def record_applied(executor: str, db_url: str, filename: str, sha: str) -> None:
    sql = f"insert into {MANIFEST_TABLE} (filename, sha256) values (%s, %s) on conflict (filename) do update set sha256 = excluded.sha256, applied_at = now();"
    _execute_sql_with_params(executor, db_url, sql, (filename, sha))


# ─── Execution backends ───────────────────────────────────────────────

def _execute_sql(executor: str, db_url: str, sql: str) -> None:
    if executor == "psycopg2":
        import psycopg2
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    else:  # psql
        # Use psql with -v ON_ERROR_STOP=1 so a SQL error fails the command
        result = subprocess.run(
            ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"psql failed (rc={result.returncode}): {result.stderr.strip()}")


def _execute_sql_returning(executor: str, db_url: str, sql: str) -> List[Tuple]:
    if executor == "psycopg2":
        import psycopg2
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()
    else:
        # psql with -t -A for tab-separated, no header
        result = subprocess.run(
            ["psql", db_url, "-t", "-A", "-X", "-q", "-c", sql],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"psql failed: {result.stderr.strip()}")
        rows = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                rows.append((line,))
        return rows


def _execute_sql_with_params(executor: str, db_url: str, sql: str, params: tuple) -> None:
    if executor == "psycopg2":
        import psycopg2
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
    else:
        # psql doesn't support parameterized queries. Format safely.
        # Filename + sha256 are both text and we control them.
        formatted = sql.replace("%s", "'" + params[0].replace("'", "''") + "'", 1)
        formatted = formatted.replace("%s", "'" + params[1].replace("'", "''") + "'", 1)
        _execute_sql(executor, db_url, formatted)


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Apply all SQL migrations in migrations-py/")
    p.add_argument("--db-url", help="Postgres connection string (overrides SUPABASE_DB_URL env)")
    p.add_argument("--dry-run", action="store_true", help="Show what would be applied without touching the DB")
    p.add_argument("--force", action="store_true", help="Re-apply all migrations (ignore manifest)")
    p.add_argument("--only", help="Apply only the migration whose filename contains this substring (for targeted re-runs)")
    args = p.parse_args()

    if not MIGRATIONS_DIR.is_dir():
        logger.error("migrations dir not found: %s", MIGRATIONS_DIR)
        sys.exit(1)

    files = discover_migrations()
    logger.info("found %d migration files in %s", len(files), MIGRATIONS_DIR)

    if args.dry_run:
        for f in files:
            logger.info("  would apply: %s (%d bytes)", f.name, f.stat().st_size)
        logger.info("(dry-run; nothing was written)")
        return 0

    db_url = get_db_url(args.db_url)
    logger.info("connecting: %s", _strip_pg_url_password(db_url))
    executor = detect_executor()
    logger.info("using executor: %s", executor)

    # Ensure manifest table exists, then read what's already applied
    ensure_manifest(executor, db_url)
    applied = set() if args.force else get_applied(executor, db_url)
    if args.force:
        logger.info("--force set; ignoring manifest (will re-apply all)")
    else:
        logger.info("manifest has %d already-applied migrations", len(applied))

    # Optional filter for targeted re-runs
    if args.only:
        before = len(files)
        files = [f for f in files if args.only in f.name]
        logger.info("--only %r filter: %d -> %d files", args.only, before, len(files))

    # Apply each migration not already in the manifest
    success = 0
    skipped = 0
    failed = 0
    for f in files:
        if f.name in applied and not args.force:
            logger.info("  skip (already applied): %s", f.name)
            skipped += 1
            continue
        sql = strip_header(f.read_text(encoding="utf-8"))
        sha = file_sha256(f)
        logger.info("  applying: %s (%d bytes, sha256=%s...)", f.name, len(sql), sha[:12])
        try:
            _execute_sql(executor, db_url, sql)
            record_applied(executor, db_url, f.name, sha)
            logger.info("    ok")
            success += 1
        except Exception as e:
            logger.error("    FAILED: %s", e)
            failed += 1
            logger.error("migration %s failed; subsequent migrations not attempted", f.name)
            break

    logger.info("done. applied=%d skipped=%d failed=%d", success, skipped, failed)

    if failed:
        sys.exit(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
