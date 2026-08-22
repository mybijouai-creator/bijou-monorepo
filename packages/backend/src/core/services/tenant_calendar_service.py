"""
Tenant Calendar Service
=======================

Multi-tenant calendar booking service that:
1. Fetches tenant-specific Cal.com credentials from database
2. Creates bookings via CalendarTool
3. Sends email confirmations to customers
4. Logs booking details for escalation handover

Author: W3J Consulting
Date: 2026-03-03
"""

import logging
from typing import Any, Dict, Optional
from datetime import datetime

from src.core.tools.calendar_tool import CalendarTool
from src.integrations.email_service import EmailService

logger = logging.getLogger(__name__)


class TenantCalendarService:
    """
    Handles calendar bookings with tenant-specific credentials.

    Flow:
    1. Fetch tenant's Cal.com config from database
    2. Create booking using their credentials
    3. Send email confirmation to customer
    4. Return booking details for escalation
    """

    def __init__(self, supabase_client=None):
        """
        Initialize service with database access.

        Args:
            supabase_client: Supabase client for DB queries
        """
        self.db = supabase_client
        self.email_service = EmailService(supabase_client)

    def _refresh_oauth_token(self, tenant_id: str, config: Dict) -> Optional[str]:
        """
        2026-08-23 FEATURE: Cal.com OAuth access tokens expire; nothing ever
        refreshed them (oauth_refresh_token was captured and stored on
        connect but never read back anywhere — grep confirmed zero usage).
        Once a tenant's token expired, booking/availability silently started
        failing with a 401 that CalendarTool swallows into a generic
        {"success": False, "error": ...} dict, with no re-auth flow.

        Uses the same OAuth2 token endpoint + client_id as the initial
        exchange (dashboard_api_simple.py's /calendar/oauth-exchange), with
        grant_type=refresh_token instead of authorization_code. Persists the
        new tokens and returns the new access token, or None on failure.
        """
        refresh_token = config.get("oauth_refresh_token")
        if not refresh_token:
            return None
        try:
            import httpx as _httpx
            CAL_CLIENT_ID = "3195ffcf36e5fbac1d894f625a96270418d36afb5578e051dae8b64330346652"
            resp = _httpx.post(
                "https://app.cal.com/api/auth/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": CAL_CLIENT_ID,
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if resp.status_code not in (200, 201):
                logger.error(f"❌ Cal.com token refresh failed for tenant {tenant_id[:8]}...: {resp.status_code} {resp.text[:200]}")
                return None
            data = resp.json()
            data = data.get("data", data)
            new_access = data.get("access_token") or data.get("accessToken")
            new_refresh = data.get("refresh_token") or data.get("refreshToken") or refresh_token
            if not new_access:
                return None
            if self.db:
                self.db.table("tenant_calendars").update({
                    "oauth_access_token": new_access,
                    "oauth_refresh_token": new_refresh,
                }).eq("tenant_id", tenant_id).execute()
            logger.info(f"✅ Refreshed Cal.com OAuth token for tenant {tenant_id[:8]}...")
            return new_access
        except Exception as e:
            logger.error(f"❌ Cal.com token refresh error for tenant {tenant_id[:8]}...: {e}")
            return None

    @staticmethod
    def _is_unauthorized(result: Dict) -> bool:
        """Detect a 401 inside CalendarTool's {"success": False, "error": str(e)} shape."""
        err = str((result or {}).get("error", ""))
        return "401" in err or "Unauthorized" in err

    def get_tenant_calendar_config(self, tenant_id: str) -> Optional[Dict]:
        """
        Fetch tenant's Cal.com configuration from database.

        Args:
            tenant_id: Tenant UUID

        Returns:
            Dict with cal_username, cal_api_key, default_event_type_id
            or None if not configured
        """
        if not self.db or not tenant_id:
            logger.warning("No database client or tenant_id provided")
            return None

        try:
            result = self.db.table("tenant_calendars")\
                .select("*")\
                .eq("tenant_id", tenant_id)\
                .eq("provider", "cal.com")\
                .eq("is_active", True)\
                .limit(1)\
                .execute()

            if result.data and len(result.data) > 0:
                config = result.data[0]
                logger.info(f"✅ Found Cal.com config for tenant {tenant_id[:8]}... (user={config.get('cal_username')})")
                return config
            else:
                logger.warning(f"❌ No Cal.com config found for tenant {tenant_id}")
                return None

        except Exception as e:
            logger.error(f"Failed to fetch calendar config for tenant {tenant_id}: {e}")
            return None

    def create_booking(
        self,
        tenant_id: str,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        start_time: str,
        property_name: Optional[str] = None,
        notes: Optional[str] = None,
        duration_minutes: int = 30
    ) -> Dict[str, Any]:
        """
        Create a calendar booking using tenant's Cal.com account.

        Args:
            tenant_id: Tenant UUID
            customer_name: Customer's name
            customer_email: Customer's email (for confirmation)
            customer_phone: Customer's phone number
            start_time: ISO 8601 datetime string (e.g., "2026-03-04T14:00:00+08:00")
            property_name: Property name / location
            notes: Additional notes for the booking
            duration_minutes: Booking duration (default 30 min)

        Returns:
            Dict with:
                - success: bool
                - booking_id: Cal.com booking ID
                - calendar_link: .ics file URL
                - confirmation_sent: bool (email sent status)
                - error: str (if failed)
        """
        # Step 1: Get tenant's calendar config
        config = self.get_tenant_calendar_config(tenant_id)

        if not config:
            return {
                "success": False,
                "error": "Calendar not configured for this tenant. Please add Cal.com credentials in dashboard."
            }

        # Step 2: Initialize CalendarTool with tenant's credentials (OAuth preferred)
        try:
            # Create temporary CalendarTool instance with tenant credentials
            calendar = CalendarTool()
            if config.get("is_oauth_connected") and config.get("oauth_access_token"):
                calendar.oauth_token  = config.get("oauth_access_token")
                calendar.username     = config.get("cal_username") or ""
                calendar._initialized = True
                logger.debug(f"Using OAuth token for tenant {tenant_id[:8]}...")
            else:
                calendar.api_key      = config.get("cal_api_key")
                calendar.username     = config.get("cal_username")
                calendar._initialized = bool(calendar.api_key)

            # Step 3: Create booking
            title = f"Property Viewing - {property_name or 'TBC'}"
            description = f"""
Property Viewing Appointment

Customer: {customer_name}
Phone: {customer_phone}
Email: {customer_email}
Property: {property_name or 'To be confirmed'}

Notes:
{notes or '(No additional notes)'}

---
Booked via Bijou AI
            """.strip()

            booking_result = calendar.create_event(
                title=title,
                start_time=start_time,
                description=description,
                attendees=[customer_email],
                event_type_id=config.get("default_event_type_id"),
                timezone="Asia/Kuala_Lumpur"
            )

            # 2026-08-23 FEATURE: retry once after a token refresh on 401 —
            # see _refresh_oauth_token's docstring for why this never existed.
            if self._is_unauthorized(booking_result) and calendar._use_oauth:
                new_token = self._refresh_oauth_token(tenant_id, config)
                if new_token:
                    calendar.oauth_token = new_token
                    booking_result = calendar.create_event(
                        title=title,
                        start_time=start_time,
                        description=description,
                        attendees=[customer_email],
                        event_type_id=config.get("default_event_type_id"),
                        timezone="Asia/Kuala_Lumpur"
                    )

            if not booking_result.get("success"):
                logger.error(f"❌ Failed to create Cal.com booking: {booking_result.get('error')}")
                return {
                    "success": False,
                    "error": f"Calendar booking failed: {booking_result.get('error')}"
                }

            # 2026-08-22 FIX: calendar_tool.py's create_event() returns a FLAT
            # dict ({"success", "booking_id", "event_link", ...}), never a
            # nested "booking" key — so booking_id was always None and every
            # confirmation link was literally ".../reschedule/None".
            booking_id = booking_result.get("booking_id")
            calendar_link = booking_result.get("event_link") or (
                f"https://cal.com/{config.get('cal_username')}/reschedule/{booking_id}"
                if booking_id else None
            )

            logger.info(f"✅ Booking created: ID={booking_id}, Link={calendar_link}")

            # Step 4: Send email confirmation (if enabled)
            confirmation_sent = False

            if config.get("send_confirmation_email", True):
                try:
                    email_result = self.email_service.send_booking_confirmation(
                        tenant_id=tenant_id,
                        customer_name=customer_name,
                        customer_email=customer_email,
                        property_name=property_name or "Property Viewing",
                        booking_date=self._format_date(start_time),
                        booking_time=self._format_time(start_time),
                        calendar_link=calendar_link,
                        duration=duration_minutes
                    )

                    confirmation_sent = email_result.get("success", False)

                    if confirmation_sent:
                        logger.info(f"✅ Booking confirmation email sent to {customer_email}")
                    else:
                        logger.warning(f"⚠️ Email confirmation failed: {email_result.get('error')}")

                except Exception as e:
                    logger.error(f"Failed to send booking confirmation email: {e}")

            # Step 5: Return booking details
            return {
                "success": True,
                "booking_id": booking_id,
                "calendar_link": calendar_link,
                "confirmation_sent": confirmation_sent,
                "start_time": start_time,
                "duration_minutes": duration_minutes,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
                "property_name": property_name
            }

        except Exception as e:
            logger.error(f"Unexpected error creating booking: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }

    def check_availability(
        self,
        tenant_id: str,
        date_from: str,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Check calendar availability using tenant's Cal.com account.

        Args:
            tenant_id: Tenant UUID
            date_from: ISO date string (e.g., "2026-03-04")
            date_to: Optional end date (defaults to date_from + 7 days)

        Returns:
            Dict with available slots or error
        """
        config = self.get_tenant_calendar_config(tenant_id)

        if not config:
            return {
                "success": False,
                "error": "Calendar not configured for this tenant"
            }

        try:
            calendar = CalendarTool()
            if config.get("is_oauth_connected") and config.get("oauth_access_token"):
                calendar.oauth_token  = config.get("oauth_access_token")
                calendar.username     = config.get("cal_username") or ""
                calendar._initialized = True
                logger.debug(f"Using OAuth token for tenant {tenant_id[:8]}... (availability check)")
            else:
                calendar.api_key      = config.get("cal_api_key")
                calendar.username     = config.get("cal_username")
                calendar._initialized = bool(calendar.api_key)

            result = calendar.get_availability(
                date_from=date_from,
                date_to=date_to,
                event_type_id=config.get("default_event_type_id")
            )

            if self._is_unauthorized(result) and calendar._use_oauth:
                new_token = self._refresh_oauth_token(tenant_id, config)
                if new_token:
                    calendar.oauth_token = new_token
                    result = calendar.get_availability(
                        date_from=date_from,
                        date_to=date_to,
                        event_type_id=config.get("default_event_type_id")
                    )

            return result

        except Exception as e:
            logger.error(f"Failed to check availability: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _format_date(self, iso_datetime: str) -> str:
        """
        Format ISO datetime to human-readable date.

        Args:
            iso_datetime: "2026-03-04T14:00:00+08:00"

        Returns:
            "Tuesday, March 4, 2026"
        """
        try:
            dt = datetime.fromisoformat(iso_datetime.replace('Z', '+00:00'))
            return dt.strftime("%A, %B %d, %Y")
        except Exception:
            return iso_datetime.split('T')[0]

    def _format_time(self, iso_datetime: str) -> str:
        """
        Format ISO datetime to human-readable time.

        Args:
            iso_datetime: "2026-03-04T14:00:00+08:00"

        Returns:
            "2:00 PM"
        """
        try:
            dt = datetime.fromisoformat(iso_datetime.replace('Z', '+00:00'))
            return dt.strftime("%I:%M %p")
        except Exception:
            return iso_datetime.split('T')[1].split('+')[0]


# ============================================================================
# Convenience function
# ============================================================================

def create_tenant_calendar_service(supabase_client=None) -> TenantCalendarService:
    """
    Factory function to create TenantCalendarService instance.

    Args:
        supabase_client: Supabase client instance

    Returns:
        TenantCalendarService instance
    """
    return TenantCalendarService(supabase_client=supabase_client)
