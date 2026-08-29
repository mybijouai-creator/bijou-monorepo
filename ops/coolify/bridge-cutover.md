# Bijou WhatsApp bridge — per-tenant cutover runbook (Fly.io → Coolify)

> One-tenant-at-a-time migration of the `packages/bridge/` Go
> service from Fly.io to Coolify. Each tenant's bridge maintains a
> live WhatsApp Web session in SQLite + the whatsmeow credentials dir.
> Losing the session = the tenant has to re-scan the QR code, which
> is a customer-facing outage.

The user said "deploy whatsapp bridge if needed" — yes, it is needed
for full Fly-to-Coolify migration. Recommended order is **backend
first, then per-tenant bridge** (see
`PRODUCTION-CUTOVER-PLAN.md` §3 step 1). The backend cutover is
covered by the main runbook; this is the bridge-specific addendum.

---

## When to run this

- After the backend Coolify stack is **green on all 9 smoke tests**
  AND the DNS cutover to `app.mybijou.xyz` is complete.
- BEFORE decommissioning the Fly.io bridge app.

If you cut the bridge before the backend, WhatsApp messages will
arrive at the bridge with no backend to forward to, and they will
sit in the queue until the backend is up.

---

## The state we need to preserve per tenant

For each tenant's bridge, we need to copy across:

| Source (Fly) | Destination (Coolify) | Why |
|---|---|---|
| `/data/bridge.db` (SQLite) | `/data/bridge.db` | The bridge's message log + per-conversation state. |
| `/data/whatsapp-session/` (whatsmeow creds dir) | `/data/whatsapp-session/` | The signed-in WhatsApp Web session. Losing this = re-QR. |
| `/data/contacts-cache/` (if present) | `/data/contacts-cache/` | The contact-list cache the bridge builds. Loss is recoverable (re-fetched on first use). |
| Fly app `name` and `region` | Coolify service `name` and project | So monitoring + alerts keep matching. |

The bridge runs as a Coolify service with a single named volume
mounted at `/data`. Coolify stores the volume in
`/data/coolify/volumes/<service-uuid>/`. We just need the data
inside `/data` to end up there.

---

## Per-tenant procedure (5-15 min per tenant)

### Step 1 — Identify the tenant + the Fly machine

```powershell
$Tenant = 'acme-clinic'  # the tenant slug
$FlyApp = "bijou-bridge-$Tenant"
flyctl machines list -a $FlyApp
```

You'll see one or more machines. For a single-tenant bridge there's
typically one. Note the `ID` (a 14-char hex).

### Step 2 — Stop the Fly bridge (gracefully)

```powershell
flyctl machines stop <machine-id> -a $FlyApp
```

This lets the bridge finish any in-flight webhook to the backend.
Wait 30 seconds, then verify the machine is stopped:

```powershell
flyctl machines list -a $FlyApp | Select-String 'stopped'
```

If it's still "started" after 60s, force-stop:

```powershell
flyctl machines kill <machine-id> -a $FlyApp
```

**Do NOT delete the machine yet.** We need its volumes.

### Step 3 — Create the Coolify service for the tenant

In the Coolify UI:

1. Go to the `bijou-prod` project.
2. "+ New Resource" → "Docker Compose" (or "Dockerfile" — same result).
3. Point at `mybijouai-creator/bijou-monorepo` (or the local path if
   you mirror the repo), branch `main`, **base directory**:
   `packages/bridge/`, **Dockerfile location**: `Dockerfile.bridge`.
4. Service name: `bijou-bridge-$Tenant` (must match the Fly app name
   for any external monitoring to keep working).
5. **Domain / port mapping:** bridge does NOT need a public port —
   only the backend talks to it. The bridge should run on the
   internal Coolify network.
6. **Persistent storage:** add a volume mounted at `/data`. Coolify
   names it for you. **This is the destination for the Fly data.**
7. **Environment variables** (override the env group):
   - `BIJOU_BACKEND_URL=https://app.mybijou.xyz` (the new
     Coolify-backed backend)
   - `BIJOU_BACKEND_API_KEY=$BRIDGE_SHARED_SECRET` (the same
     shared secret the backend verifies; it must match what
     `migrate-secrets-to-coolify.ps1` set on the backend)
   - `DB_PATH=/data/bridge.db`
   - `WHATSAPP_SESSION_PATH=/data/whatsapp-session`
   - `TENANT_ID=$Tenant`
8. **Health check:** the same one in `Dockerfile.bridge`'s
   `HEALTHCHECK` line (`/app/bridge --health-check`).
9. Click **Deploy**. The container will start, fail the health check
   (no DB yet), and Coolify will mark it unhealthy. That's expected.
10. **Stop it again** before copying data:
    ```powershell
    # from the agent's project root
    .\ops\coolify\coolify-volume-snapshot.ps1 -ServiceName "bijou-bridge-$Tenant" -Action stop
    ```
    (If this script doesn't exist yet, use the Coolify UI: click the
    service, "Stop".)

### Step 4 — Copy the Fly volume data into the Coolify volume

The Fly volume path on the host is:
`/var/lib/docker/volumes/<fly-volume-name>/_data/`

The Coolify volume path on the host is:
`/data/coolify/volumes/<coolify-service-uuid>/_data/`

Both are on the same VPS if Coolify is on the same machine as Fly
(the Bijou setup uses Coolify as the primary deploy target on a
single VPS, so this holds). If they're on different machines, use
`rsync` over SSH or `scp` with an intermediate staging area.

```bash
# On the VPS, as root
FLY_VOL=/var/lib/docker/volumes/production_bridge_data_${TENANT}/_data
COOL_VOL=/data/coolify/volumes/${COOLIFY_SVC_UUID}/_data

# Preserve the WhatsApp session — DO NOT touch the session dir
# contents; just copy them as-is. The whatsmeow library refuses to
# re-attach to a session that was modified while disconnected.
rsync -aH --info=progress2 "$FLY_VOL/bridge.db"        "$COOL_VOL/bridge.db"
rsync -aH --info=progress2 "$FLY_VOL/whatsapp-session/" "$COOL_VOL/whatsapp-session/"
[ -d "$FLY_VOL/contacts-cache" ] && rsync -aH --info=progress2 "$FLY_VOL/contacts-cache/" "$COOL_VOL/contacts-cache/"
```

The flags:
- `-a` = archive (recursive + perms + times + symlinks)
- `-H` = preserve hard-links (the whatsmeow session may have some)
- `--info=progress2` = visible progress

Verify the SQLite is not corrupt before starting Coolify:
```bash
sqlite3 "$COOL_VOL/bridge.db" "PRAGMA integrity_check;"
# Expect: ok
```

If integrity_check returns anything else, restore from a Fly
snapshot:
```bash
flyctl volumes snapshots list -a $FlyApp
flyctl volumes snapshots restore <snapshot-id> -a $FlyApp
# Then re-rsync.
```

### Step 5 — Start the Coolify bridge and verify

1. In the Coolify UI, click the service, "Start" (or
   `coolify-volume-snapshot.ps1 -Action start`).
2. Watch the logs for the first 60 seconds. Expected sequence:
   ```
   [INFO] bridge v1.0.0 starting
   [INFO] loading WhatsApp session from /data/whatsapp-session
   [INFO] session re-attached (no QR scan required)
   [INFO] webhook listener ready on :8080
   [INFO] health check OK
   ```
3. If you see "session expired, please re-scan QR", the session dir
   was not copied cleanly. **Stop, restore from Fly snapshot, retry.**
4. From the Bijou dashboard, navigate to the tenant's "Bridge" tab.
   The "Bridge connected" indicator should be green within 30s.
5. Send a test WhatsApp message to the tenant's connected number.
   The Bijou backend should receive the webhook, the bridge should
   get the AI reply, and the customer should see the reply.

### Step 6 — Update DNS for the bridge (if the bridge has a public URL)

Some bridges have a per-tenant public webhook URL
(`https://bridge.<tenant>.mybijou.xyz/...`) that the WhatsApp
business API or Telnyx hits. If the bridge URL changed in the
Coolify cutover:

```powershell
.\ops\coolify\porkbun-cutover.ps1 `
    -Domain 'mybijou.xyz' `
    -Subdomain "bridge-$Tenant" `
    -RecordType 'CNAME' `
    -NewTarget "coolify-bijou-bridge-$Tenant.getbijou.xyz" `
    -ConfirmCutover
```

For multi-tenant batch:
```powershell
$tenants = @('acme-clinic', 'gentle-dental', 'sunrise-cafe')
$batch = $tenants | ForEach-Object {
    @{ Domain = 'mybijou.xyz'; Subdomain = "bridge-$_"; Type = 'CNAME'; Target = "coolify-bijou-bridge-$_.getbijou.xyz" }
}
.\ops\coolify\porkbun-cutover.ps1 -Batch $batch -ConfirmCutover
```

### Step 7 — Decommission the Fly bridge

After the tenant has been on Coolify for at least 24 hours with no
issues, delete the Fly app:

```powershell
flyctl apps destroy $FlyApp --yes
```

**Do NOT do this before 24 hours.** The Fly app is the rollback
target if the Coolify bridge has a subtle session-attachment bug
that only shows up after some real traffic.

---

## Batch mode (10+ tenants)

For the full 1-tenant-per-15-min operation, write a small wrapper:

```powershell
# cutover-all-bridges.ps1
$tenants = flyctl apps list --json | ConvertFrom-Json | Where-Object { $_.Name -like 'bijou-bridge-*' } | ForEach-Object { $_.Name -replace '^bijou-bridge-', '' }
foreach ($t in $tenants) {
    Write-Host "=== Cutting over $t ===" -ForegroundColor Cyan
    # ... do steps 2-6 per tenant
}
```

This is intentionally a manual script. The per-tenant volume copy
needs a human eye on the `integrity_check` output, and the 24-hour
wait per tenant is not compressible.

---

## Rollback per tenant

If the Coolify bridge has a problem after cutover:

1. **Stop the Coolify bridge** (UI or script).
2. **Re-create the Fly bridge** if it was destroyed (it shouldn't
   have been — see step 7's 24h rule):
   ```powershell
   flyctl apps create $FlyApp
   flyctl volumes create bridge_data --size 1 -a $FlyApp
   flyctl deploy ... # the old bridge image from the previous commit
   ```
3. **Copy the Coolify volume back to Fly** (the same `rsync` in
   reverse).
4. **Point the DNS back** (Porkbun: run the rollback path in
   `porkbun-cutover.ps1`).
5. **Investigate the root cause** before re-attempting.

---

## What can go wrong (and the early-warning signs)

| Symptom | Likely cause | Mitigation |
|---|---|---|
| `session expired, please re-scan QR` | The session dir was not copied atomically, or the whatsmeow library was a different version | Re-rsync with `rsync -aH`; verify the source Fly machine was fully stopped before copy. |
| `backend rejected webhook: 401` | `BRIDGE_SHARED_SECRET` mismatch | The bridge is sending a different secret than the backend expects. Re-check the env vars in both the bridge service and the backend env group. |
| `SQLite database is locked` | Both Fly and Coolify bridges pointed at the same volume briefly | Confirm Fly is stopped. The Coolify volume must be the only one with that bridge.db open. |
| Customer reports the bridge replies but doesn't see incoming messages | The webhook URL changed and Telnyx is still pointing at the old URL | Update the Telnyx webhook to the new bridge URL. |
| `health check failed: bridge binary not executable` | The Coolify distroless image doesn't have shell, and the health check tries to run a shell command | The current `Dockerfile.bridge` health check is `/app/bridge --health-check` which is a direct exec, not a shell. Verify in the build logs. |
| Per-tenant `BRIDGE_SHARED_SECRET` is the same across tenants | The bridge code probably reads the env var, not a per-tenant secret. That's by design. | Make sure the backend's `BRIDGE_SHARED_SECRET` matches. Per-tenant isolation is via `TENANT_ID`, not a separate key. |
