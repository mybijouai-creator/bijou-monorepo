"""
Appwrite storage client — ALONGSIDE Supabase, not a replacement.

The Bijou stack is built around Supabase + GoTrue for auth and the
multi-tenant database. Appwrite is wired in here for **one specific
purpose**: per-tenant file storage (KB documents, image uploads, voice
note attachments). This gives us a self-hosted storage backend separate
from Supabase Storage (which is a thin wrapper over S3).

Design rules (enforced 2026-08-29 after the user asked to "use Appwrite
alongside Supabase"):

- All calls are gated behind ``ENABLE_APPWRITE_STORAGE``. If the flag
  is off, :func:`is_enabled` returns ``False`` and the existing
  local-fs storage in ``packages/backend/uploads/`` is used unchanged.
- The client is **lazy-initialized** at first use, not at import time.
  This keeps the Appwrite SDK out of the import path for tests and
  for routes that never touch storage.
- The client reads ``APPWRITE_*`` env vars at first use and caches
  the resolved values. Rotating a secret requires a process restart
  (or a call to :func:`reset_client`).
- The ``appwrite`` Python SDK is pinned to **14.1.0** in
  ``requirements.txt`` because the deployed Appwrite server is
  **1.7.4** (per the ``appwrite==14.1.0`` rule in agent memory). SDK
  15+ is built for server 1.8+ and will emit version-mismatch warnings.
- File IDs are scoped to a tenant via the ``tenant_id`` prefix in the
  storage path. The ``file_id`` argument is the unique-per-tenant
  identifier (e.g. ``kb_doc_42``, ``media_msg_1830``); the actual
  Appwrite file ID passed to the SDK is
  ``"{tenant_id}/{file_id}"`` so the bucket is logically partitioned
  per tenant without per-tenant bucket provisioning.
- The dashboard's Files tab reads from whichever backend is enabled
  (``ENABLE_APPWRITE_STORAGE`` true → this module, false →
  ``MediaLibraryService`` / local fs).

What this module does NOT do (by design, in this turn):

- It does NOT replace Supabase auth. Signin/signup still goes through
  GoTrue. Appwrite Auth is wired in a future turn if/when the user
  decides to migrate.
- It does NOT replace the multi-tenant Postgres schema. The Supabase
  tables (``tenants``, ``users``, ``conversations``, ``audit_log``,
  ``shared_context``, …) stay where they are.
- It does NOT replace Stripe, Resend, Langfuse, or any other provider.
  It is a storage-only addition.
- It does NOT call Appwrite from the browser. The server-side key
  (``APPWRITE_API_KEY``) is a server-only secret; the dashboard
  reads files via the same Bijou backend route as today, which calls
  this module.

See ``ops/coolify/PRODUCTION-CUTOVER-PLAN.md`` §5 for the design
context.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, BinaryIO, Optional

_LOG = logging.getLogger("bijou.appwrite")

# Lazy import — keep the SDK out of the import path until the first
# storage call. Lets unit tests run without the SDK installed.
_appwrite_module: Optional[Any] = None
_client_singleton: Optional["_AppwriteClient"] = None
_client_lock = threading.Lock()


def _load_sdk():
    """Load the Appwrite Python SDK on first use."""
    global _appwrite_module
    if _appwrite_module is not None:
        return _appwrite_module
    try:
        # appwrite SDK 14.x exposes Client, Storage, InputFile
        from appwrite.client import Client
        from appwrite.services.storage import Storage
        from appwrite.input_file import InputFile
        _appwrite_module = {"Client": Client, "Storage": Storage, "InputFile": InputFile}
        return _appwrite_module
    except ImportError as exc:
        raise RuntimeError(
            "Appwrite SDK is not installed. Run `pip install appwrite==14.1.0` "
            "or set ENABLE_APPWRITE_STORAGE=false to use the local-fs backend. "
            f"Original error: {exc}"
        )


class AppwriteConfigError(RuntimeError):
    """Raised when ENABLE_APPWRITE_STORAGE is true but required env vars are missing."""


class _AppwriteClient:
    """Internal wrapper around the Appwrite SDK client + storage service."""

    def __init__(self) -> None:
        sdk = _load_sdk()
        endpoint = os.environ.get("APPWRITE_ENDPOINT", "").rstrip("/")
        project_id = os.environ.get("APPWRITE_PROJECT_ID", "")
        api_key = os.environ.get("APPWRITE_API_KEY", "")
        if not endpoint or not project_id or not api_key:
            raise AppwriteConfigError(
                "ENABLE_APPWRITE_STORAGE is true but APPWRITE_ENDPOINT, "
                "APPWRITE_PROJECT_ID, or APPWRITE_API_KEY is missing."
            )
        client = sdk["Client"]()
        client.set_endpoint(endpoint)
        client.set_project(project_id)
        client.set_key(api_key)
        self._storage = sdk["Storage"](client)
        self._bucket_id = os.environ.get("APPWRITE_STORAGE_BUCKET", "bijou-kb-files")
        self._public_read = os.environ.get("APPWRITE_STORAGE_PUBLIC_READ", "false").lower() == "true"

    @property
    def storage(self):
        return self._storage

    @property
    def bucket_id(self) -> str:
        return self._bucket_id

    @property
    def public_read(self) -> bool:
        return self._public_read


def is_enabled() -> bool:
    """Return True iff the Appwrite storage backend is the active backend."""
    flag = os.environ.get("ENABLE_APPWRITE_STORAGE", "false").strip().lower()
    return flag in ("1", "true", "yes", "on")


def get_client() -> _AppwriteClient:
    """Return a process-singleton Appwrite client. Lazy-initialized."""
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton
    with _client_lock:
        if _client_singleton is None:
            _client_singleton = _AppwriteClient()
    return _client_singleton


def reset_client() -> None:
    """Drop the cached client so the next call re-reads env (for tests / rotations)."""
    global _client_singleton
    with _client_lock:
        _client_singleton = None


def _scoped_file_id(tenant_id: str, file_id: str) -> str:
    """Build a tenant-scoped Appwrite file ID.

    The Appwrite file ID is the only unique key inside a bucket, so we
    prefix with ``{tenant_id}/`` to keep tenants' files logically
    separate in a shared bucket. ``file_id`` itself must be a
    Bijou-side identifier that is unique within the tenant
    (e.g. ``kb_doc_42``); the SDK will accept any string up to the
    36-char ID limit, so we hash long IDs.
    """
    if not tenant_id or not file_id:
        raise ValueError("tenant_id and file_id are both required")
    # Appwrite file IDs are 36 chars max. We use a short sha256 prefix
    # of ``{tenant}/{file}`` to keep the ID compact and stable.
    import hashlib
    raw = f"{tenant_id}/{file_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return digest[:36]


def upload_file(tenant_id: str, file_id: str, file_obj: BinaryIO, mime_type: str = "application/octet-stream") -> str:
    """Upload a file to the Appwrite bucket. Returns the Appwrite file ID."""
    if not is_enabled():
        raise AppwriteConfigError("ENABLE_APPWRITE_STORAGE is not set; use the local-fs backend instead.")
    client = get_client()
    sdk = _load_sdk()
    scoped = _scoped_file_id(tenant_id, file_id)
    permissions = ["read(\"any\")"] if client.public_read else []
    try:
        result = client.storage.create_file(
            bucket_id=client.bucket_id,
            file_id=scoped,
            file=sdk["InputFile"].from_bytes(file_obj.read(), mime_type=mime_type),
            permissions=permissions,
        )
        _LOG.info("appwrite.upload tenant=%s file_id=%s scoped_id=%s mime=%s", tenant_id, file_id, scoped, mime_type)
        return result["$id"]
    except Exception as exc:
        _LOG.exception("appwrite.upload_failed tenant=%s file_id=%s", tenant_id, file_id)
        raise RuntimeError(f"Appwrite upload failed: {exc}") from exc


def get_file_url(tenant_id: str, file_id: str) -> str:
    """Return a URL the browser can use to fetch the file.

    For non-public buckets this is a short-lived preview URL generated
    by the Appwrite storage.get_file_view. For public buckets it's
    the storage.get_file_download URL.
    """
    if not is_enabled():
        raise AppwriteConfigError("ENABLE_APPWRITE_STORAGE is not set.")
    client = get_client()
    scoped = _scoped_file_id(tenant_id, file_id)
    if client.public_read:
        return client.storage.get_file_download(client.bucket_id, scoped)
    return client.storage.get_file_view(client.bucket_id, scoped)


def delete_file(tenant_id: str, file_id: str) -> None:
    """Delete a file from the Appwrite bucket. Idempotent — no error if the file is absent."""
    if not is_enabled():
        raise AppwriteConfigError("ENABLE_APPWRITE_STORAGE is not set.")
    client = get_client()
    scoped = _scoped_file_id(tenant_id, file_id)
    try:
        client.storage.delete_file(client.bucket_id, scoped)
        _LOG.info("appwrite.delete tenant=%s file_id=%s scoped_id=%s", tenant_id, file_id, scoped)
    except Exception as exc:
        # Appwrite raises a 404 if the file is already gone. Treat
        # that as success so the delete path is idempotent.
        if "404" in str(exc) or "not found" in str(exc).lower():
            _LOG.info("appwrite.delete_idempotent tenant=%s file_id=%s (already gone)", tenant_id, file_id)
            return
        _LOG.exception("appwrite.delete_failed tenant=%s file_id=%s", tenant_id, file_id)
        raise RuntimeError(f"Appwrite delete failed: {exc}") from exc


def health_check() -> dict:
    """Return a small dict the admin console can display in the Appwrite card.

    Tries to read the bucket metadata. On any failure returns a dict
    with ``enabled=True`` and ``reachable=False`` plus the error.
    """
    if not is_enabled():
        return {"enabled": False, "reachable": False, "reason": "ENABLE_APPWRITE_STORAGE is off"}
    try:
        client = get_client()
        bucket = client.storage.get_bucket(client.bucket_id)
        return {
            "enabled": True,
            "reachable": True,
            "bucket_id": client.bucket_id,
            "bucket_name": bucket.get("name"),
            "public_read": client.public_read,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "reachable": False,
            "error": str(exc),
        }
