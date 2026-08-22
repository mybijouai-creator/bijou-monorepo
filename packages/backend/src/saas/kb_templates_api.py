"""
Industry KB Templates API
=========================
REST endpoints for the "fill-in-the-blank" industry onboarding templates.

When a client picks their vertical (e.g. "property", "fnb") we serve them a
structured template with named placeholders.  They fill in their own values
(agent name, price range, operating hours, etc.) and hit "Apply".  The system
then generates real knowledge_base entries + updates their client_config —
so their AI assistant is ready in under 7 minutes.

Endpoints:
  GET  /api/kb-templates/industries            → list available verticals
  GET  /api/kb-templates/{vertical}            → fetch full template for a vertical
  POST /api/kb-templates/{vertical}/preview    → render template with supplied variables (dry-run)
  POST /api/kb-templates/{vertical}/save       → save filled variables (progress) without applying
  POST /api/kb-templates/{vertical}/apply      → apply template → creates KB entries in DB
  GET  /api/kb-templates/instances             → list this tenant's template instances
  GET  /api/kb-templates/instances/{id}        → get one instance with filled vars
  DELETE /api/kb-templates/instances/{id}/reset → clear filled vars, start over

All endpoints require X-Tenant-ID header (standard Bijou auth).
"""

from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kb-templates", tags=["kb-templates"])


# ---------------------------------------------------------------------------
# Auth Dependency
# ---------------------------------------------------------------------------

def _get_db(request: Request):
    """Re-use the Supabase client already attached to app.state by bijou.py."""
    if hasattr(request.app.state, "supabase"):
        return request.app.state.supabase
    # Fallback: import directly
    try:
        from src.core.bijou import get_supabase
        return get_supabase()
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")


def _require_tenant(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="X-Tenant-ID header required")
    return x_tenant_id


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ApplyTemplateRequest(BaseModel):
    filled_variables: dict[str, str]
    """Key-value map matching the template's variable keys, e.g.
       {"AGENT_NAME": "Ahmad", "BUSINESS_NAME": "Century21 MK", ...}"""


class SaveProgressRequest(BaseModel):
    filled_variables: dict[str, str]


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _substitute(text: str, variables: dict[str, str]) -> str:
    """Replace all {{VAR_KEY}} occurrences in text with supplied values.
    Unknown placeholders are left as-is so the client sees what is missing.
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))  # keep original if missing

    return _PLACEHOLDER_RE.sub(_replace, text)


def _render_faq(faq_list: list[dict], variables: dict[str, str]) -> list[dict]:
    rendered = []
    for faq in faq_list:
        rendered.append({
            **faq,
            "answer": _substitute(faq.get("answer_template", ""), variables),
        })
    return rendered


def _completion_pct(template_vars: list[dict], filled: dict[str, str]) -> int:
    """Return 0-100 based on how many required variables are filled."""
    required = [v["key"] for v in template_vars if v.get("required")]
    optional = [v["key"] for v in template_vars if not v.get("required")]
    if not required:
        return 100

    req_done = sum(1 for k in required if filled.get(k, "").strip())
    opt_done = sum(1 for k in optional if filled.get(k, "").strip())

    # Required fields = 80%, optional = 20%
    pct = int((req_done / len(required)) * 80)
    if optional:
        pct += int((opt_done / len(optional)) * 20)
    return min(pct, 100)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/industries")
async def list_industries(
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """Return all available industry templates (id, vertical, name, description)."""
    db = _get_db(request)
    try:
        result = (
            db.table("industry_kb_templates")
            .select("id, vertical, sub_vertical, template_name, description, sort_order")
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        return {"industries": result.data or []}
    except Exception as exc:
        logger.error("list_industries error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{vertical}")
async def get_template(
    vertical: str,
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """
    Fetch the full template for a vertical slug (e.g. 'property', 'fnb').
    Also returns any previously saved progress for this tenant.
    """
    db = _get_db(request)
    try:
        tmpl_res = (
            db.table("industry_kb_templates")
            .select("*")
            .eq("vertical", vertical.lower())
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not tmpl_res.data:
            raise HTTPException(
                status_code=404,
                detail=f"No template found for vertical '{vertical}'",
            )
        template = tmpl_res.data[0]

        # Check for existing instance (saved progress)
        instance_res = (
            db.table("tenant_kb_template_instances")
            .select("id, filled_variables, completion_pct, is_complete, is_applied")
            .eq("tenant_id", tenant_id)
            .eq("template_id", template["id"])
            .limit(1)
            .execute()
        )
        existing_instance = instance_res.data[0] if instance_res.data else None

        return {
            "template": template,
            "saved_progress": existing_instance,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_template error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{vertical}/preview")
async def preview_template(
    vertical: str,
    body: ApplyTemplateRequest,
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """
    Dry-run: render the full template with the supplied variables.
    Returns rendered FAQ answers, greeting, after-hours message — without
    saving anything to the database.  Use this to show a live preview of what
    the AI will say before the client commits.
    """
    db = _get_db(request)
    try:
        tmpl_res = (
            db.table("industry_kb_templates")
            .select("*")
            .eq("vertical", vertical.lower())
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not tmpl_res.data:
            raise HTTPException(status_code=404, detail=f"No template for '{vertical}'")

        template = tmpl_res.data[0]
        variables = body.filled_variables

        rendered_faq = _render_faq(template.get("faq_template", []), variables)
        rendered_greeting = _substitute(template.get("greeting_template", ""), variables)
        rendered_after_hours = _substitute(template.get("after_hours_template", ""), variables)

        pct = _completion_pct(template.get("variables", []), variables)

        # Surface missing required fields
        missing_required = [
            v["key"]
            for v in template.get("variables", [])
            if v.get("required") and not variables.get(v["key"], "").strip()
        ]

        return {
            "completion_pct": pct,
            "missing_required": missing_required,
            "is_ready": len(missing_required) == 0,
            "rendered": {
                "faq": rendered_faq,
                "greeting": rendered_greeting,
                "after_hours": rendered_after_hours,
                "escalation_triggers": template.get("escalation_triggers", []),
                "qualification_questions": template.get("qualification_questions", []),
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("preview_template error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{vertical}/save")
async def save_progress(
    vertical: str,
    body: SaveProgressRequest,
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """Save filled variables as draft (does NOT create KB entries yet)."""
    db = _get_db(request)
    try:
        tmpl_res = (
            db.table("industry_kb_templates")
            .select("id, variables")
            .eq("vertical", vertical.lower())
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not tmpl_res.data:
            raise HTTPException(status_code=404, detail=f"No template for '{vertical}'")

        template = tmpl_res.data[0]
        pct = _completion_pct(template.get("variables", []), body.filled_variables)

        # Upsert instance
        instance_res = (
            db.table("tenant_kb_template_instances")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("template_id", template["id"])
            .limit(1)
            .execute()
        )

        payload = {
            "tenant_id": tenant_id,
            "template_id": template["id"],
            "filled_variables": body.filled_variables,
            "completion_pct": pct,
            "is_complete": pct >= 80,
        }

        if instance_res.data:
            db.table("tenant_kb_template_instances").update(payload).eq(
                "id", instance_res.data[0]["id"]
            ).execute()
            instance_id = instance_res.data[0]["id"]
        else:
            create_res = db.table("tenant_kb_template_instances").insert(payload).execute()
            instance_id = create_res.data[0]["id"]

        return {
            "instance_id": instance_id,
            "completion_pct": pct,
            "is_complete": pct >= 80,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("save_progress error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{vertical}/apply")
async def apply_template(
    vertical: str,
    body: ApplyTemplateRequest,
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """
    Apply the template to this tenant:
    1. Validate all required variables are provided.
    2. Render FAQ pairs and insert into knowledge_bases.
    3. Update the tenant's client_configs.system_prompt_vars with industry + business info.
    4. Mark the template instance as applied.
    Returns a summary of what was created.
    """
    db = _get_db(request)
    variables = body.filled_variables

    try:
        tmpl_res = (
            db.table("industry_kb_templates")
            .select("*")
            .eq("vertical", vertical.lower())
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not tmpl_res.data:
            raise HTTPException(status_code=404, detail=f"No template for '{vertical}'")

        template = tmpl_res.data[0]

        # Validate required fields
        missing = [
            v["key"]
            for v in template.get("variables", [])
            if v.get("required") and not variables.get(v["key"], "").strip()
        ]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required fields: {', '.join(missing)}",
            )

        # --- Build KB entries ---
        kb_entries = []

        # 1. FAQ answers per category
        category_buckets: dict[str, list[dict]] = {}
        for faq in template.get("faq_template", []):
            cat = faq.get("category", "general")
            category_buckets.setdefault(cat, []).append(faq)

        for category, faqs in category_buckets.items():
            content_lines = []
            for faq in faqs:
                q = faq.get("question", "")
                a = _substitute(faq.get("answer_template", ""), variables)
                content_lines.append(f"Q: {q}\nA: {a}")

            kb_entries.append({
                "tenant_id": tenant_id,
                "source_type": "template",
                "title": f"FAQ – {category.replace('_', ' ').title()}",
                "content": "\n\n".join(content_lines),
                "category": category,
                "tags": [vertical, "template", category],
                "is_active": True,
            })

        # 2. Qualification / BANT questions as KB entry
        qual_questions = template.get("qualification_questions", [])
        if qual_questions:
            qual_content = "Lead Qualification Questions (BANT):\n\n"
            for q in qual_questions:
                qual_content += f"Step {q.get('step', '?')} ({q.get('bant', '')}):\n"
                qual_content += f"  Question: {q.get('question', '')}\n"
                qual_content += f"  High-value signal: {q.get('high_value_signal', '')}\n\n"
            kb_entries.append({
                "tenant_id": tenant_id,
                "source_type": "template",
                "title": "Lead Qualification – BANT Questions",
                "content": qual_content,
                "category": "qualification",
                "tags": [vertical, "template", "bant", "qualification"],
                "is_active": True,
            })

        # 3. Escalation triggers as KB entry
        escalation_triggers = template.get("escalation_triggers", [])
        if escalation_triggers:
            esc_content = "Escalation Triggers & Agent Hints:\n\n"
            for esc in escalation_triggers:
                esc_content += f"Type: {esc.get('type', '')} – {esc.get('id', '')}\n"
                kw = ", ".join(esc.get("trigger_keywords", []))
                esc_content += f"  Keywords: {kw}\n"
                esc_content += f"  AI Reply: {_substitute(esc.get('ai_reply', ''), variables)}\n"
                esc_content += f"  Action: {esc.get('action', '')}\n"
                human_hint = esc.get("human_hint", "")
                if human_hint:
                    esc_content += f"  Agent Hint: {human_hint}\n"
                esc_content += "\n"
            kb_entries.append({
                "tenant_id": tenant_id,
                "source_type": "template",
                "title": "Escalation Triggers & Playbook",
                "content": esc_content,
                "category": "escalation",
                "tags": [vertical, "template", "escalation"],
                "is_active": True,
            })

        # 4. Greeting + after-hours as a single KB entry
        greeting = _substitute(template.get("greeting_template", ""), variables)
        after_hours = _substitute(template.get("after_hours_template", ""), variables)
        if greeting or after_hours:
            auto_reply_content = ""
            if greeting:
                auto_reply_content += f"GREETING MESSAGE:\n{greeting}\n\n"
            if after_hours:
                auto_reply_content += f"AFTER-HOURS MESSAGE:\n{after_hours}"
            kb_entries.append({
                "tenant_id": tenant_id,
                "source_type": "template",
                "title": "Auto-Reply Messages",
                "content": auto_reply_content.strip(),
                "category": "auto_reply",
                "tags": [vertical, "template", "greeting", "auto_reply"],
                "is_active": True,
            })

        # --- Wipe old template KB entries for this tenant + vertical (idempotent reapply)
        db.table("knowledge_bases").delete().eq("tenant_id", tenant_id).eq(
            "source_type", "template"
        ).containedBy("tags", [vertical]).execute()

        # --- Insert new KB entries
        insert_res = db.table("knowledge_bases").insert(kb_entries).execute()
        kb_ids = [row["id"] for row in (insert_res.data or [])]

        # 2026-08-22 FIX: knowledge_bases is never read by the live chat
        # pipeline — Bijou._generate_response() builds knowledge_context via
        # KnowledgeUploader.get_combined_knowledge(), which only queries
        # knowledge_documents (see knowledge_upload.py:433-438). Every prior
        # "Apply to My AI — Go Live" completed with a success screen but
        # ZERO change to what the AI actually says to a customer. Mirror the
        # same entries into knowledge_documents (the schema kb_import_api.py
        # already uses) so the wizard's content is actually usable in chat.
        # Wipe-then-reinsert on uploaded_by="kb_template" for idempotent
        # reapply, matching the knowledge_bases wipe above.
        db.table("knowledge_documents").delete().eq("tenant_id", tenant_id).eq(
            "uploaded_by", "kb_template"
        ).execute()
        if kb_entries:
            now_iso = datetime.utcnow().isoformat()
            doc_rows = [
                {
                    "tenant_id": tenant_id,
                    "filename": entry["title"],
                    "file_type": "text/plain",
                    "file_size_kb": round(len(entry["content"].encode()) / 1024, 2),
                    "content_extracted": entry["content"],
                    "uploaded_by": "kb_template",
                    "uploaded_at": now_iso,
                    "metadata": {"source": "kb_template", "vertical": vertical, "category": entry.get("category")},
                }
                for entry in kb_entries
            ]
            db.table("knowledge_documents").insert(doc_rows).execute()

        # --- Update client_configs.system_prompt_vars
        cfg_res = (
            db.table("client_configs")
            .select("id, system_prompt_vars")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        new_vars: dict[str, Any] = {}
        if cfg_res.data:
            new_vars = cfg_res.data[0].get("system_prompt_vars") or {}

        new_vars.update({
            "industry": vertical,
            "business_name": variables.get("BUSINESS_NAME", new_vars.get("business_name", "")),
            "agent_name": variables.get("AGENT_NAME", new_vars.get("agent_name", "")),
            "operating_hours": variables.get("OPERATING_HOURS", new_vars.get("operating_hours", "")),
            "areas_covered": variables.get("AREAS_COVERED", ""),
            "payment_methods": variables.get("PAYMENT_METHODS", ""),
        })

        if cfg_res.data:
            db.table("client_configs").update({"system_prompt_vars": new_vars}).eq(
                "tenant_id", tenant_id
            ).execute()
        else:
            db.table("client_configs").insert(
                {"tenant_id": tenant_id, "system_prompt_vars": new_vars, "is_active": True}
            ).execute()

        # --- Mark instance as applied
        await _upsert_instance_applied(db, tenant_id, template["id"], variables, kb_ids)

        logger.info(
            "KB template applied: tenant=%s vertical=%s kb_entries=%d",
            tenant_id, vertical, len(kb_ids),
        )

        return {
            "success": True,
            "kb_entries_created": len(kb_ids),
            "kb_entry_ids": kb_ids,
            "categories": list(category_buckets.keys()),
            "message": (
                f"✅ {len(kb_ids)} knowledge base entries created for '{vertical}'. "
                "Your AI assistant is now ready!"
            ),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("apply_template error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def _upsert_instance_applied(
    db, tenant_id: str, template_id: str, variables: dict, kb_ids: list
):
    payload = {
        "tenant_id": tenant_id,
        "template_id": template_id,
        "filled_variables": variables,
        "completion_pct": 100,
        "is_complete": True,
        "is_applied": True,
        "kb_entry_ids": kb_ids,
    }
    instance_res = (
        db.table("tenant_kb_template_instances")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("template_id", template_id)
        .limit(1)
        .execute()
    )
    if instance_res.data:
        db.table("tenant_kb_template_instances").update(payload).eq(
            "id", instance_res.data[0]["id"]
        ).execute()
    else:
        db.table("tenant_kb_template_instances").insert(payload).execute()


@router.get("/instances")
async def list_instances(
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """List all template instances for this tenant (saved progress)."""
    db = _get_db(request)
    try:
        result = (
            db.table("tenant_kb_template_instances")
            .select(
                "id, template_id, completion_pct, is_complete, is_applied, created_at, updated_at, "
                "industry_kb_templates(vertical, template_name)"
            )
            .eq("tenant_id", tenant_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return {"instances": result.data or []}
    except Exception as exc:
        logger.error("list_instances error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/instances/{instance_id}")
async def get_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """Get a single template instance with filled variables."""
    db = _get_db(request)
    try:
        result = (
            db.table("tenant_kb_template_instances")
            .select("*, industry_kb_templates(*)")
            .eq("id", instance_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Instance not found")
        return {"instance": result.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_instance error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/instances/{instance_id}/reset")
async def reset_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """Clear all saved variables for an instance (start over)."""
    db = _get_db(request)
    try:
        result = (
            db.table("tenant_kb_template_instances")
            .select("id")
            .eq("id", instance_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Instance not found")

        db.table("tenant_kb_template_instances").update({
            "filled_variables": {},
            "completion_pct": 0,
            "is_complete": False,
            "is_applied": False,
            "kb_entry_ids": [],
        }).eq("id", instance_id).execute()

        return {"success": True, "message": "Instance reset. Start filling in your details again."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reset_instance error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
