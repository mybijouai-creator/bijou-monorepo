"""
Enhanced Escalation API - Phase 5
==================================

FastAPI endpoints for enhanced escalation management with
multi-channel notifications and resume detection.

Author: W3J Consulting
Date: 2026-02-11
Phase: 5 - Human Escalation Enhancements
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional, Dict, List
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from loguru import logger

from .handover_system import HandoverSystem, EscalationPriority, EscalationStatus
from .escalation_notifier import EscalationNotifier, NotificationChannel


router = APIRouter(prefix="/api/escalations", tags=["escalations"])


class CreateEscalationRequest(BaseModel):
    """Request to create an escalation"""
    tenant_id: str
    customer_jid: str
    reason: str
    escalation_type: str = "general"
    priority: str = "normal"
    confidence_score: Optional[float] = None
    trigger_keywords: Optional[List[str]] = None
    conversation_context: Optional[Dict] = None


class ResumeRequest(BaseModel):
    """Request to resume AI after escalation"""
    escalation_id: str
    tenant_id: str
    customer_satisfaction_score: Optional[int] = None
    resolution_notes: Optional[str] = None


class EscalationActionRequest(BaseModel):
    """Request to log an action on escalation"""
    escalation_id: str
    tenant_id: str
    action_type: str
    performed_by: str
    notes: Optional[str] = None
    action_data: Optional[Dict] = None


class EnhancedEscalationAPI:
    """Enhanced Escalation API with notifications"""

    def __init__(
        self,
        supabase_client,
        handover_system: HandoverSystem,
        notifier: EscalationNotifier
    ):
        """
        Initialize escalation API

        Args:
            supabase_client: Supabase client
            handover_system: HandoverSystem instance
            notifier: EscalationNotifier instance
        """
        self.db = supabase_client
        self.handover = handover_system
        self.notifier = notifier


# Global instance
escalation_api: Optional[EnhancedEscalationAPI] = None


def init_escalation_api(
    supabase_client,
    handover_system: HandoverSystem,
    notifier: EscalationNotifier
):
    """Initialize the global escalation API"""
    global escalation_api
    escalation_api = EnhancedEscalationAPI(
        supabase_client,
        handover_system,
        notifier
    )
    return escalation_api


@router.post("/create")
async def create_escalation(
    request: CreateEscalationRequest,
    background_tasks: BackgroundTasks
):
    """
    Create a new escalation with multi-channel notifications

    Process:
    1. Create escalation record
    2. Select appropriate agent
    3. Send notifications (email, WhatsApp, SMS, Telegram)
    4. Return escalation ID
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        # Convert priority string to enum
        priority = EscalationPriority(request.priority)

        # Create escalation using existing handover system
        escalation_id = await escalation_api.handover.create_escalation(
            tenant_id=request.tenant_id,
            customer_jid=request.customer_jid,
            reason=request.reason,
            priority=priority,
            metadata={
                "escalation_type": request.escalation_type,
                "confidence_score": request.confidence_score,
                "trigger_keywords": request.trigger_keywords or [],
                "conversation_context": request.conversation_context
            }
        )

        if not escalation_id:
            raise HTTPException(status_code=500, detail="Failed to create escalation")

        # Get escalation details for notification
        esc_result = escalation_api.db.table("escalations").select("*").eq("tenant_id", request.tenant_id).eq("id", escalation_id).execute()

        if not esc_result.data:
            raise HTTPException(status_code=404, detail="Escalation not found after creation")

        escalation_data = esc_result.data[0]

        # Get assigned agent details
        assigned_agent_id = escalation_data.get("assigned_agent_id")
        if assigned_agent_id:
            agent_result = escalation_api.db.table("handover_agents").select("*").eq("tenant_id", request.tenant_id).eq("id", assigned_agent_id).execute()

            if agent_result.data:
                agent_data = agent_result.data[0]

                # Send notifications in background
                background_tasks.add_task(
                    notify_agent_about_escalation,
                    escalation_id,
                    request.tenant_id,
                    agent_data,
                    escalation_data
                )

        return {
            "success": True,
            "escalation_id": escalation_id,
            "priority": request.priority,
            "assigned_to": escalation_data.get("assigned_to"),
            "message": "Escalation created and agent notified"
        }

    except Exception as e:
        logger.error(f"Error creating escalation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def notify_agent_about_escalation(
    escalation_id: str,
    tenant_id: str,
    agent_data: Dict,
    escalation_data: Dict
):
    """Background task to notify agent"""
    try:
        results = await escalation_api.notifier.notify_agent(
            escalation_id,
            tenant_id,
            agent_data,
            escalation_data
        )

        logger.info(f"Notification sent for escalation {escalation_id}: {results}")

    except Exception as e:
        logger.error(f"Error notifying agent: {e}")


@router.post("/resume")
async def resume_ai_after_escalation(request: ResumeRequest):
    """
    Resume AI responses after human escalation resolved

    Triggered by:
    - Agent sending '@bijou resume' command
    - Manual resolution via API
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        # Get escalation
        esc_result = escalation_api.db.table("escalations").select("*").eq(
            "id", request.escalation_id
        ).eq("tenant_id", request.tenant_id).execute()

        if not esc_result.data:
            raise HTTPException(status_code=404, detail="Escalation not found")

        escalation = esc_result.data[0]

        # Update escalation status
        updates = {
            "status": EscalationStatus.RESOLVED.value,
            "resolved_at": datetime.utcnow().isoformat(),
            "resumed_at": datetime.utcnow().isoformat(),
            "resolution_notes": request.resolution_notes
        }

        if request.customer_satisfaction_score:
            updates["customer_satisfaction_score"] = request.customer_satisfaction_score

        escalation_api.db.table("escalations").update(updates).eq(
            "id", request.escalation_id
        ).execute()

        # Log action
        await log_escalation_action(
            request.escalation_id,
            request.tenant_id,
            "resolved",
            "system",
            notes="AI responses resumed"
        )

        # Send confirmation message to customer
        customer_jid = escalation.get("chat_jid")
        # TODO: Send "I'm back! How can I help?" message via bridge

        return {
            "success": True,
            "escalation_id": request.escalation_id,
            "message": "AI responses resumed",
            "customer_jid": customer_jid
        }

    except Exception as e:
        logger.error(f"Error resuming AI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/action")
async def log_action(request: EscalationActionRequest):
    """
    Log an action on an escalation

    Action types:
    - claimed: Agent claimed the escalation
    - message_sent: Agent sent message to customer
    - note_added: Internal note added
    - status_changed: Status updated
    - resolved: Escalation resolved
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        await log_escalation_action(
            request.escalation_id,
            request.tenant_id,
            request.action_type,
            request.performed_by,
            request.action_data,
            request.notes
        )

        return {
            "success": True,
            "message": f"Action '{request.action_type}' logged"
        }

    except Exception as e:
        logger.error(f"Error logging action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def log_escalation_action(
    escalation_id: str,
    tenant_id: str,
    action_type: str,
    performed_by: str,
    action_data: Optional[Dict] = None,
    notes: Optional[str] = None
):
    """Helper to log escalation action"""
    try:
        action_record = {
            "escalation_id": escalation_id,
            "tenant_id": tenant_id,
            "action_type": action_type,
            "performed_by": performed_by,
            "action_data": action_data,
            "notes": notes,
            "created_at": datetime.utcnow().isoformat()
        }

        escalation_api.db.table("escalation_actions").insert(action_record).execute()
        logger.debug(f"Logged action {action_type} for escalation {escalation_id}")

    except Exception as e:
        logger.error(f"Error logging action: {e}")
        raise


@router.get("/list")
async def list_escalations(
    tenant_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None
):
    """
    List escalations for a tenant with optional filters
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        # Convert string params to enums if provided
        status_enum = EscalationStatus(status) if status else None
        priority_enum = EscalationPriority(priority) if priority else None

        # Get escalations using handover system
        escalations = escalation_api.handover.get_queue(
            tenant_id=tenant_id,
            status=status_enum,
            priority=priority_enum,
            assigned_to=assigned_to
        )

        # Ensure all records are JSON serializable (convert enums)
        for esc in escalations:
            if isinstance(esc.get("status"), Enum):
                esc["status"] = esc["status"].value
            if isinstance(esc.get("priority"), Enum):
                esc["priority"] = esc["priority"].value

        return {
            "success": True,
            "escalations": escalations,
            "count": len(escalations)
        }

    except Exception as e:
        logger.error(f"Error listing escalations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/details/{escalation_id}")
async def get_escalation_details(
    escalation_id: str,
    tenant_id: str
):
    """
    Get complete escalation details including actions and notifications
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        # Use PostgreSQL function for complete details
        result = escalation_api.db.rpc(
            "get_escalation_details",
            {"p_escalation_id": escalation_id}
        ).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Escalation not found")

        details = result.data[0]

        # Verify tenant access
        if details.get("tenant_id") != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Ensure enums are serialized to strings for React dashboard
        from enum import Enum
        safe_escalation = {}
        for k, v in details.items():
            if isinstance(v, Enum):
                safe_escalation[k] = v.value
            else:
                safe_escalation[k] = v

        return {
            "success": True,
            "escalation": safe_escalation
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting escalation details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_escalation_statistics(
    tenant_id: str,
    period_days: int = 30
):
    """
    Get escalation statistics for a tenant
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        # Use PostgreSQL function for stats
        result = escalation_api.db.rpc(
            "get_escalation_stats",
            {
                "p_tenant_id": tenant_id,
                "p_period_days": period_days
            }
        ).execute()

        stats = result.data[0] if result.data else {}

        # Ensure enums are serialized to strings
        from enum import Enum
        safe_stats = {}
        for k, v in stats.items():
            if isinstance(v, Enum):
                safe_stats[k] = v.value
            else:
                safe_stats[k] = v

        return {
            "success": True,
            "stats": safe_stats,
            "period_days": period_days
        }

    except Exception as e:
        logger.error(f"Error getting escalation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect")
async def detect_escalation_intent(
    tenant_id: str,
    message: str,
    customer_jid: str,
    emotion: Optional[str] = None
):
    """
    Detect if a message should trigger escalation

    Returns:
    - should_escalate: bool
    - reason: str
    - priority: str
    - confidence_score: float
    """
    if not escalation_api:
        raise HTTPException(status_code=500, detail="Escalation API not initialized")

    try:
        # Use handover system detection
        should_escalate, reason, priority = escalation_api.handover.should_escalate(
            message=message,
            emotion=emotion
        )

        # Calculate confidence score (simple heuristic for now)
        confidence = 0.9 if "speak to human" in message.lower() else 0.7

        return {
            "should_escalate": should_escalate,
            "reason": reason,
            "priority": priority.value if should_escalate else "normal",
            "confidence_score": confidence,
            "trigger_keywords": escalation_api.handover.escalation_keywords
        }

    except Exception as e:
        logger.error(f"Error detecting escalation: {e}")
        raise HTTPException(status_code=500, detail=str(e))
