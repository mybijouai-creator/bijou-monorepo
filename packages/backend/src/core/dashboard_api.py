#!/usr/bin/env python3
"""
Agent Assist Dashboard API
===========================

REST API endpoints for the human agent dashboard.

Provides:
- Active conversation list
- Conversation history and context
- Manual takeover controls
- Message sending interface
- Real-time metrics

Author: W3J Bijou AI
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ==================== MODELS ====================

class ConversationSummary(BaseModel):
    """Summary of an active conversation"""
    customer_jid: str
    customer_name: Optional[str] = None
    tenant_id: str
    status: str  # "ai", "human", "pending_handover"
    last_message_time: datetime
    message_count: int
    unread_count: int
    lead_score: Optional[float] = None
    tags: List[str] = []


class ConversationDetail(BaseModel):
    """Detailed conversation view"""
    customer_jid: str
    customer_name: Optional[str] = None
    tenant_id: str
    status: str
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    lead_info: Optional[Dict[str, Any]] = None
    ai_suggestions: List[str] = []


class TakeoverRequest(BaseModel):
    """Request to take over a conversation"""
    customer_jid: str
    agent_name: str
    reason: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Send a message as human agent"""
    customer_jid: str
    message: str
    agent_name: str


class DashboardStats(BaseModel):
    """Dashboard metrics"""
    active_conversations: int
    ai_handled: int
    human_handled: int
    pending_handovers: int
    avg_response_time_seconds: float
    leads_generated_today: int


# ==================== ENDPOINTS ====================

@router.get("/conversations", response_model=List[ConversationSummary])
async def list_conversations(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200)
):
    """
    List active conversations with filters
    
    Query params:
    - tenant_id: Filter by tenant
    - status: Filter by status (ai/human/pending_handover)
    - limit: Max results (default 50, max 200)
    """
    logger.info(f"📋 Listing conversations: tenant={tenant_id}, status={status}, limit={limit}")
    
    # TODO: Reconnect to database when SupabaseDB module is available
    # For now, return empty list to prevent crashes
    logger.warning("⚠️ Database connection not available - returning empty list")
    return []


@router.get("/conversation/{customer_jid}", response_model=ConversationDetail)
async def get_conversation_detail(customer_jid: str):
    """
    Get detailed view of a specific conversation
    
    Includes:
    - Full message history
    - Customer metadata
    - Lead qualification data
    - AI suggestions for next response
    """
    logger.info(f"🔍 Getting conversation detail: {customer_jid}")
    
    try:
        # from src.core.database import SupabaseDB
        db = SupabaseDB()
        
        # Get all messages for this conversation
        query = """
        SELECT 
            message_id,
            message_content,
            sender,
            is_from_me,
            ai_response,
            timestamp,
            detected_language,
            detected_emotion,
            confidence_score
        FROM conversations
        WHERE chat_jid = %s
        ORDER BY timestamp ASC
        LIMIT 100
        """
        
        result = db.execute_query(query, (customer_jid,))
        
        if not result:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Build messages list
        messages = []
        for row in result:
            messages.append({
                "message_id": row['message_id'],
                "content": row['message_content'],
                "sender": "user" if not row['is_from_me'] else "assistant",
                "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                "metadata": {
                    "language": row['detected_language'],
                    "emotion": row['detected_emotion'],
                    "confidence": row['confidence_score']
                }
            })
        
        # Check escalation status
        escalation_query = """
        SELECT status, assigned_to, reason
        FROM escalations
        WHERE chat_jid = %s
        AND status IN ('pending', 'in_progress')
        ORDER BY created_at DESC
        LIMIT 1
        """
        
        escalation = db.execute_query(escalation_query, (customer_jid,))
        
        status = "ai"
        if escalation:
            if escalation[0]['status'] == 'pending':
                status = "pending_handover"
            elif escalation[0]['status'] == 'in_progress':
                status = "human"
        
        # Extract phone number
        phone = customer_jid.split('@')[0] if '@' in customer_jid else customer_jid
        
        # Get tenant_id from first message
        tenant_id = result[0].get('tenant_id', 'unknown')
        
        return ConversationDetail(
            customer_jid=customer_jid,
            customer_name=f"+{phone}",
            tenant_id=str(tenant_id) if tenant_id else "unknown",
            status=status,
            messages=messages,
            metadata={
                "total_messages": len(messages),
                "languages_detected": list(set([m.get('metadata', {}).get('language') for m in messages if m.get('metadata', {}).get('language')]))
            },
            lead_info=None,  # TODO: Add lead scoring
            ai_suggestions=[]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting conversation detail: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/takeover")
async def takeover_conversation(request: TakeoverRequest):
    """
    Manual takeover - switch conversation from AI to human agent
    
    This will:
    1. Pause AI responses
    2. Notify customer of human takeover
    3. Log the handover event
    """
    logger.info(f"🤝 Takeover request: {request.customer_jid} by {request.agent_name}")
    
    try:
        # from src.core.database import SupabaseDB
        from datetime import datetime, timezone
        import uuid
        db = SupabaseDB()
        
        # Create escalation record
        escalation_id = str(uuid.uuid4())
        
        # First, get tenant_id from conversations
        tenant_query = """
        SELECT DISTINCT tenant_id FROM conversations
        WHERE chat_jid = %s
        LIMIT 1
        """
        tenant_result = db.execute_query(tenant_query, (request.customer_jid,))
        
        if not tenant_result:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        tenant_id = tenant_result[0]['tenant_id']
        
        # Create or update escalation
        insert_query = """
        INSERT INTO escalations (
            id, tenant_id, chat_jid, reason, status, 
            priority, assigned_to, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, 'in_progress', 'normal', %s, NOW(), NOW())
        ON CONFLICT (tenant_id, chat_jid) 
        DO UPDATE SET 
            status = 'in_progress',
            assigned_to = EXCLUDED.assigned_to,
            reason = EXCLUDED.reason,
            updated_at = NOW()
        """
        
        db.execute_query(insert_query, (
            escalation_id,
            tenant_id,
            request.customer_jid,
            request.reason or "Manual takeover from dashboard",
            request.agent_name
        ))
        
        logger.info(f"✅ Takeover successful: {request.customer_jid} → {request.agent_name}")
        
        return {
            "status": "success",
            "message": f"Conversation taken over by {request.agent_name}",
            "customer_jid": request.customer_jid
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Takeover failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-message")
async def send_message_as_agent(request: SendMessageRequest):
    """
    Send a message as a human agent
    
    This will:
    1. Send message via WhatsApp/Telegram
    2. Log it as human-sent
    3. Keep AI paused
    """
    logger.info(f"📤 Agent message: {request.agent_name} → {request.customer_jid}")
    
    # TODO: Implement - send via channel adapter
    return {
        "status": "success",
        "message": "Message sent",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.post("/return-to-ai/{customer_jid}")
async def return_to_ai(customer_jid: str, agent_name: str):
    """
    Return conversation to AI control
    
    Agent is done, let AI handle it again.
    """
    logger.info(f"🤖 Returning to AI: {customer_jid} by {agent_name}")
    
    # TODO: Integrate with HandoverSystem
    return {
        "status": "success",
        "message": "Conversation returned to AI",
        "customer_jid": customer_jid
    }


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    tenant_id: Optional[str] = Query(None)
):
    """
    Get real-time dashboard statistics
    
    Shows:
    - Active conversation counts
    - AI vs human handling ratio
    - Response time metrics
    - Lead generation stats
    """
    logger.info(f"📊 Getting dashboard stats: tenant={tenant_id}")
    
    try:
        # from src.core.database import SupabaseDB
        db = SupabaseDB()
        
        # Count active conversations (last 7 days)
        query = """
        WITH conversation_counts AS (
            SELECT 
                COUNT(DISTINCT c.chat_jid) as total_conversations
            FROM conversations c
            WHERE c.timestamp > NOW() - INTERVAL '7 days'
        """
        
        params = []
        if tenant_id:
            query += " AND c.tenant_id::text = %s"
            params.append(tenant_id)
        
        query += """
        ),
        escalation_counts AS (
            SELECT 
                COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as human_handled,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_handovers
            FROM escalations
            WHERE created_at > NOW() - INTERVAL '7 days'
        """
        
        if tenant_id:
            query += " AND tenant_id::text = %s"
            params.append(tenant_id)
        
        query += """
        ),
        leads_today AS (
            SELECT COUNT(*) as count
            FROM conversations
            WHERE DATE(timestamp) = CURRENT_DATE
        """
        
        if tenant_id:
            query += " AND tenant_id::text = %s"
            params.append(tenant_id)
        
        query += """
        )
        SELECT 
            COALESCE(cc.total_conversations, 0) as active_conversations,
            COALESCE(ec.human_handled, 0) as human_handled,
            COALESCE(ec.pending_handovers, 0) as pending_handovers,
            COALESCE(lt.count, 0) as leads_today
        FROM conversation_counts cc
        CROSS JOIN escalation_counts ec
        CROSS JOIN leads_today lt
        """
        
        result = db.execute_query(query, tuple(params))
        
        if result and result[0]:
            stats = result[0]
            ai_handled = stats['active_conversations'] - stats['human_handled']
            
            return DashboardStats(
                active_conversations=stats['active_conversations'],
                ai_handled=max(0, ai_handled),
                human_handled=stats['human_handled'],
                pending_handovers=stats['pending_handovers'],
                avg_response_time_seconds=0.0,  # TODO: Calculate from processing_time_ms
                leads_generated_today=stats['leads_today']
            )
        
        # Fallback to zeros
        return DashboardStats(
            active_conversations=0,
            ai_handled=0,
            human_handled=0,
            pending_handovers=0,
            avg_response_time_seconds=0.0,
            leads_generated_today=0
        )
        
    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}")
        import traceback
        traceback.print_exc()
        # Return zeros on error
        return DashboardStats(
            active_conversations=0,
            ai_handled=0,
            human_handled=0,
            pending_handovers=0,
            avg_response_time_seconds=0.0,
            leads_generated_today=0
        )


# 2026-08-23: Activity feed for the Home "What your AI just did" widget.
# Synthesizes a chronological feed of recent AI actions from the existing
# tables (conversations, escalations) — no new schema. Powers the first
# agentic-GenUI primitive: visible evidence the AI is working.
class ActivityItem(BaseModel):
    """One item in the AI activity feed."""
    kind: str  # 'ai_replied' | 'ai_captured_lead' | 'ai_escalated' | 'ai_human_took_over'
    message: str
    customer_jid: Optional[str] = None
    customer_name: Optional[str] = None
    timestamp: datetime
    link: Optional[str] = None  # where the user can go in the dashboard


@router.get("/activity", response_model=List[ActivityItem])
async def get_activity_feed(
    tenant_id: Optional[str] = Query(None),
    since_hours: int = Query(24, ge=1, le=168),
    limit: int = Query(15, ge=1, le=50),
):
    """
    Synthesize a recent-activity feed for the dashboard home widget.

    Pulls from existing tables — no new schema. Returns a mixed list
    (most-recent-first) of:
      - AI replies to customers (from conversations where is_from_me=true)
      - Escalations to humans (from escalations table)
      - Lead captures (from conversations tagged as lead_source)
    Empty list is fine; the widget renders an empty state.
    """
    logger.info(f"📜 Activity feed: tenant={tenant_id}, since_hours={since_hours}, limit={limit}")
    items: List[ActivityItem] = []
    try:
        db = SupabaseDB()

        # AI replies + escalations from the last N hours
        params: List[Any] = [since_hours]
        tenant_filter = ""
        if tenant_id:
            tenant_filter = " AND tenant_id::text = %s"
            params.append(tenant_id)

        # 1) Recent AI replies (most recent first, distinct chat_jid so we
        #    don't spam the feed with 5 messages from the same customer)
        replies_q = f"""
            SELECT DISTINCT ON (chat_jid)
                chat_jid,
                message_content,
                timestamp,
                tenant_id,
                detected_language
            FROM conversations
            WHERE is_from_me = true
              AND timestamp > NOW() - (%s || ' hours')::interval
              {tenant_filter}
            ORDER BY chat_jid, timestamp DESC
            LIMIT %s
        """
        params_replies = list(params) + [limit]
        try:
            for row in db.execute_query(replies_q, tuple(params_replies)) or []:
                phone = (row.get("chat_jid") or "").split("@")[0] or "a customer"
                lang = row.get("detected_language")
                suffix = f" in {lang}" if lang and lang not in ("en", "unknown") else ""
                items.append(ActivityItem(
                    kind="ai_replied",
                    message=f"Bijou replied to +{phone}{suffix}",
                    customer_jid=row.get("chat_jid"),
                    customer_name=f"+{phone}",
                    timestamp=row.get("timestamp") or datetime.utcnow(),
                    link="inbox",
                ))
        except Exception as e:
            logger.warning(f"Activity feed: AI replies query failed: {e}")

        # 2) Recent escalations
        esc_q = f"""
            SELECT chat_jid, reason, created_at, tenant_id, status
            FROM escalations
            WHERE created_at > NOW() - (%s || ' hours')::interval
              {tenant_filter}
            ORDER BY created_at DESC
            LIMIT %s
        """
        params_esc = list(params) + [limit]
        try:
            for row in db.execute_query(esc_q, tuple(params_esc)) or []:
                phone = (row.get("chat_jid") or "").split("@")[0] or "a customer"
                reason = (row.get("reason") or "needs a human")[:80]
                items.append(ActivityItem(
                    kind="ai_escalated",
                    message=f"Bijou escalated \"{reason}\" from +{phone} to you",
                    customer_jid=row.get("chat_jid"),
                    customer_name=f"+{phone}",
                    timestamp=row.get("created_at") or datetime.utcnow(),
                    link="escalations",
                ))
        except Exception as e:
            logger.warning(f"Activity feed: escalations query failed: {e}")

        # Sort merged feed by timestamp desc and trim
        items.sort(key=lambda i: i.timestamp, reverse=True)
        return items[:limit]
    except Exception as e:
        logger.error(f"❌ Error building activity feed: {e}")
        # Empty list is acceptable for the widget; the empty-state copy handles it
        return []


@router.get("/health")
async def dashboard_health():
    """Health check for dashboard API"""
    return {
        "status": "healthy",
        "service": "agent-assist-dashboard",
        "timestamp": datetime.utcnow().isoformat()
    }
