# Backend scripts

Operational tools for the backend. These are NOT part of the runtime
and are not auto-loaded by the FastAPI app. Each script is invoked
manually from a developer shell that has access to the Bijou
backend's `.env` (so it can use the Supabase service-role key).

## `apply_migrations.py` — apply SQL migrations to Supabase Postgres

**When to use:** after pulling new code that adds SQL files to
`migrations-py/`, after creating a new Supabase project, or to fix
the 3 critical failures the self-test catches
(`/api/self-test/summary` → "new_tables_exist" + others).

**What it does:** walks every `.sql` file in
`packages/backend/migrations-py/` in lexical order, applies each in
its own transaction, and records successful applications in a
manifest table (`public.schema_migrations`). Idempotent: re-running
skips already-applied files. Never drops, never deletes, never
truncates (every migration in this repo is additive).

### Quick start

```bash
# 1. Find your Supabase connection string:
#    Supabase dashboard -> Project Settings -> Database ->
#    Connection string -> URI
#    Looks like: postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
#
# 2. Add to your .env (gitignored):
echo 'SUPABASE_DB_URL=postgresql://postgres.lrwzlujomukzjykafmic:YOUR_PASSWORD@aws-0-.../postgres' >> .env

# 3. Dry-run to see what would be applied:
cd packages/backend
python -m scripts.apply_migrations --dry-run

# 4. Real run:
python -m scripts.apply_migrations

# 5. Re-apply a single migration (after fixing the SQL):
python -m scripts.apply_migrations --only add_message_reasons.sql

# 6. Force re-apply everything (ignores manifest):
python -m scripts.apply_migrations --force
```

### Why it exists

The Supabase REST API (used by the runtime) only allows DML, not
DDL. To create new tables you need a direct Postgres connection.
This script gives you one command that does the right thing for
every migration in the repo, with idempotency and a safety net.

It also re-runs cleanly: each migration is its own transaction,
and the manifest records what's been applied.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | all migrations applied (or already in manifest) |
| 1 | bad arguments / missing db url |
| 2 | connection failed / no executor available |
| 3 | a migration failed (the rest are not attempted) |

## `seed_demo_thread.py` — populate a tenant with a realistic cross-channel thread

**When to use:** before a sales demo, after onboarding a new tenant who
wants to see Bijou in action immediately, or for QA.

**What it does:** inserts 9 (or 6) cross-channel conversation turns
into `public.shared_context` and 4 reasoning rows into
`public.message_reasons` for a given `(tenant_id, phone)` pair.

### Quick start

```bash
# From packages/backend/, with the venv active and .env sourced:
cd packages/backend
python -m scripts.seed_demo_thread \
    --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \
    --phone +60123456789 \
    --dry-run                       # see what would be written

# Real run
python -m scripts.seed_demo_thread \
    --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \
    --phone +60123456789

# Support scenario
python -m scripts.seed_demo_thread \
    --tenant-id 607690ec-4ff7-4ef4-b98e-bfb00442fe95 \
    --phone +60123456789 \
    --scenario support
```

### Output

```
2026-08-23  INFO  verifying tenant exists ...
2026-08-23  INFO    tenant ok
2026-08-23  INFO  purging prior demo data for this (tenant, phone) ...
2026-08-23  INFO  inserting 9 shared_context rows ...
2026-08-23  INFO    9 rows inserted
2026-08-23  INFO  inserting reasoning rows ...
2026-08-23  INFO    4 reasoning rows inserted
2026-08-23  INFO  done.
2026-08-23  INFO  preview: https://app.mybijou.xyz/static/cross-channel-demo.html
```

### Safety

- **Idempotent:** re-running with the same (tenant, phone) deletes
  the prior demo data first, then re-inserts. Same script + same
  inputs = same output.
- **Tenant must exist:** the script refuses to write to a non-existent
  tenant_id. This prevents orphaned data.
- **Refuses placeholder inputs:** a tenant_id starting with `00000000`
  or a phone starting with `+0` is rejected as a typo / test pattern.
- **Validates every row:** each scenario row's `channel` and `role` are
  checked against the same enums the API enforces (`{whatsapp,
  telegram, voice, sms, email}` and `{user, assistant, system}`).
- **Single transaction:** if the insert fails partway, the prior rows
  are not committed. The script exits non-zero.
- **Dry-run mode:** `--dry-run` prints every row it would write,
  without touching the DB. Use this first.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | bad arguments (bad UUID, bad phone, bad scenario) |
| 2 | missing env (`SUPABASE_URL` or `SUPABASE_SERVICE_KEY` not set) |
| 3 | tenant not found |
| 4 | database error (insert failed, RLS rejected, etc.) |

### Why it exists beyond demos

This script is also the **A2A integration test that runs against
real Supabase**. The unit tests in `tests/unit/test_shared_context.py`
prove the API behaves correctly with mocks. This script proves the
data flows through real Supabase, real RLS, and the real schema
end-to-end. If a future migration changes the schema, running this
script against staging is the smoke test.

## Adding new scripts

- Place in this directory (`packages/backend/scripts/`)
- Follow the pattern: `argparse` for inputs, `sys.exit(N)` for errors
- Document in this README
- If the script uses a destructive operation, support `--dry-run`
