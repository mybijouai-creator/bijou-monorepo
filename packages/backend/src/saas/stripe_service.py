"""
Bijou AI - Stripe Payment Integration
======================================

Handles all payment operations:
- Create Stripe customers
- Create checkout sessions
- Process webhooks
- Manage subscriptions
- Generate invoices

Author: W3J Bijou AI
Version: 1.0.0
"""

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

import stripe
from supabase import create_client

from src.saas.email_service import get_email_service

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


class StripePaymentService:
    """Service for Stripe payment operations"""

    def __init__(self):
        self.supabase = self._get_supabase()
        self.email_service = get_email_service()
        self.public_url = (os.getenv("PUBLIC_URL") or os.getenv("APP_URL", "")).rstrip("/")

        if not stripe.api_key:
            logger.warning("⚠️ STRIPE_SECRET_KEY not set - payment features disabled")

    def _get_supabase(self):
        """Initialize Supabase client"""
        supabase_url = os.getenv("SUPABASE_URL", "").strip('"')
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip('"')

        if not supabase_url or not supabase_key:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

        return create_client(supabase_url, supabase_key)

    def create_or_get_customer(self, tenant_id: str) -> Optional[str]:
        """
        Create Stripe customer or get existing one

        Args:
            tenant_id: Tenant UUID

        Returns:
            str: Stripe customer ID
        """
        try:
            # Get tenant
            result = self.supabase.table("tenants").select("*").eq("id", tenant_id).execute()

            if not result.data:
                logger.error(f"Tenant {tenant_id} not found")
                return None

            tenant = result.data[0]

            # Check if customer already exists
            if tenant.get("stripe_customer_id"):
                return tenant["stripe_customer_id"]

            # Create new Stripe customer
            customer = stripe.Customer.create(
                email=tenant["email"],
                name=tenant["business_name"],
                metadata={
                    "tenant_id": tenant_id,
                    "business_name": tenant["business_name"]
                }
            )

            # Save customer ID to database
            self.supabase.table("tenants").update({
                "stripe_customer_id": customer.id,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", tenant_id).execute()

            logger.info(f"✅ Created Stripe customer {customer.id} for {tenant['business_name']}")
            return customer.id

        except Exception as e:
            logger.error(f"Failed to create Stripe customer: {e}", exc_info=True)
            return None

    def create_checkout_session(
        self,
        tenant_id: str,
        plan_code: str,
        billing_period: str = "monthly"
    ) -> Optional[Dict[str, Any]]:
        """
        Create Stripe Checkout session for subscription

        Args:
            tenant_id: Tenant UUID
            plan_code: Plan code (starter, professional, enterprise)
            billing_period: monthly or yearly

        Returns:
            dict: Session data with checkout URL
        """
        try:
            # Get plan details
            result = self.supabase.table("subscription_plans").select("*").eq("plan_code", plan_code).execute()

            if not result.data:
                logger.error(f"Plan {plan_code} not found")
                return None

            plan = result.data[0]

            # Get or create Stripe customer
            customer_id = self.create_or_get_customer(tenant_id)
            if not customer_id:
                return None

            # Get Stripe price ID
            if billing_period == "yearly":
                price_id = plan.get("stripe_price_id_yearly")
            else:
                price_id = plan.get("stripe_price_id_monthly")

            if not price_id:
                logger.error(f"No Stripe price ID for {plan_code} ({billing_period})")
                return None

            # Create checkout session with Malaysian payment methods
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card", "fpx", "duitnow_qr", "google_pay"],
                line_items=[{
                    "price": price_id,
                    "quantity": 1
                }],
                mode="subscription",
                success_url=f"{self.public_url}/api/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{self.public_url}/static/login.html?canceled=true",
                metadata={
                    "tenant_id": tenant_id,
                    "plan_code": plan_code,
                    "billing_period": billing_period
                }
            )

            logger.info(f"✅ Created checkout session {session.id} for tenant {tenant_id}")

            return {
                "session_id": session.id,
                "checkout_url": session.url,
                "customer_id": customer_id
            }

        except Exception as e:
            logger.error(f"Failed to create checkout session: {e}", exc_info=True)
            return None

    def handle_successful_payment(self, session_id: str) -> bool:
        """
        Handle successful payment from checkout session

        Args:
            session_id: Stripe checkout session ID

        Returns:
            bool: True if handled successfully
        """
        try:
            # Retrieve session
            session = stripe.checkout.Session.retrieve(session_id)

            tenant_id = session.metadata.get("tenant_id")
            plan_code = session.metadata.get("plan_code")
            billing_period = session.metadata.get("billing_period")

            if not tenant_id:
                logger.error("No tenant_id in session metadata")
                return False

            # Get subscription
            subscription = stripe.Subscription.retrieve(session.subscription)

            # Update tenant record
            self.supabase.table("tenants").update({
                "stripe_subscription_id": subscription.id,
                "subscription_status": "active",
                "is_trial": False,
                "plan": plan_code,
                "subscription_start_date": datetime.utcnow().isoformat(),
                "current_period_end": datetime.fromtimestamp(subscription.current_period_end).isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", tenant_id).execute()

            # Record transaction
            self._record_transaction(
                tenant_id=tenant_id,
                stripe_payment_intent_id=session.payment_intent,
                stripe_invoice_id=subscription.latest_invoice,
                amount_cents=session.amount_total,
                currency=session.currency,
                status="succeeded",
                plan_name=plan_code,
                billing_period=billing_period
            )

            # Get tenant info for email
            tenant_result = self.supabase.table("tenants").select("*").eq("id", tenant_id).execute()
            if tenant_result.data:
                tenant = tenant_result.data[0]

                # Send payment confirmation email
                invoice = stripe.Invoice.retrieve(subscription.latest_invoice)

                self.email_service.send_payment_confirmation(
                    to=tenant["email"],
                    business_name=tenant["business_name"],
                    plan_name=plan_code.title(),
                    amount=f"${session.amount_total / 100:.2f}",
                    invoice_url=invoice.invoice_pdf if invoice else ""
                )

                # Send dashboard access email with direct link
                dashboard_url = (
                    f"{self.public_url}/static/dashboard.html?tenant_id={tenant_id}"
                )
                self.email_service.send_dashboard_access_email(
                    to=tenant["email"],
                    business_name=tenant["business_name"],
                    dashboard_url=dashboard_url,
                )

            logger.info(f"✅ Payment successful for tenant {tenant_id} - upgraded to {plan_code}")
            return True

        except Exception as e:
            logger.error(f"Failed to handle successful payment: {e}", exc_info=True)
            return False

    def handle_webhook(self, payload: bytes, sig_header: str) -> bool:
        """
        Handle Stripe webhook events

        Args:
            payload: Raw request body
            sig_header: Stripe-Signature header

        Returns:
            bool: True if handled successfully
        """
        if not STRIPE_WEBHOOK_SECRET:
            logger.error("❌ STRIPE_WEBHOOK_SECRET not set in environment")
            return False

        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )

            logger.info(f"📨 Stripe webhook received: {event['type']}")

            # Handle different event types
            if event["type"] == "checkout.session.completed":
                session = event["data"]["object"]
                self.handle_successful_payment(session["id"])

            elif event["type"] == "invoice.payment_succeeded":
                invoice = event["data"]["object"]
                self._handle_invoice_paid(invoice)

            elif event["type"] == "invoice.payment_failed":
                invoice = event["data"]["object"]
                self._handle_invoice_failed(invoice)

            elif event["type"] == "customer.subscription.updated":
                subscription = event["data"]["object"]
                self._handle_subscription_updated(subscription)

            elif event["type"] == "customer.subscription.deleted":
                subscription = event["data"]["object"]
                self._handle_subscription_cancelled(subscription)

            return True

        except stripe.error.SignatureVerificationError as e:
            # Stripe signature verification failed - likely wrong webhook secret
            logger.error(
                f"❌ Stripe webhook signature verification failed | "
                f"error={str(e)[:200]} | "
                f"sig_header={'present' if sig_header else 'missing'} | "
                f"secret_configured={'yes' if STRIPE_WEBHOOK_SECRET else 'no'} | "
                f"secret_prefix={STRIPE_WEBHOOK_SECRET[:10] if STRIPE_WEBHOOK_SECRET else 'none'}... | "
                f"payload_size={len(payload)} bytes"
            )
            logger.warning(
                "💡 Fix: Check STRIPE_WEBHOOK_SECRET in Fly secrets matches Stripe Dashboard → Webhooks → Signing secret. "
                "Must be whsec_live_... for production, not whsec_test_..."
            )
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected webhook error: {type(e).__name__}: {e}", exc_info=True)
            return False

    def create_portal_session(
        self,
        tenant_id: str,
        return_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a Stripe Customer Portal session.

        The Customer Portal is a hosted Stripe page where the customer
        can: update payment method, see invoices, change plan,
        cancel subscription. The user returns to `return_url`
        (defaults to the dashboard billing tab) when done.

        Args:
            tenant_id: Tenant UUID
            return_url: Where Stripe sends the user back when they
                click "back to [app]". Default: the dashboard billing tab.

        Returns:
            dict: {"url": "https://billing.stripe.com/...", "session_id": "..."}
            or None on failure.
        """
        try:
            customer_id = self.create_or_get_customer(tenant_id)
            if not customer_id:
                return None

            # Default the return URL to the dashboard's Billing section.
            if not return_url:
                base = (self.public_url or "https://app.mybijou.xyz").rstrip("/")
                return_url = f"{base}/dashboard#billing"

            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )

            logger.info(
                f"✅ Created Customer Portal session for tenant {tenant_id}"
            )
            return {
                "url": session.url,
                "session_id": session.id,
            }
        except Exception as e:
            logger.error(f"Failed to create Customer Portal session: {e}", exc_info=True)
            return None

    def cancel_subscription(self, tenant_id: str) -> bool:
        """Cancel subscription for a tenant"""
        try:
            # Get tenant
            result = self.supabase.table("tenants").select("stripe_subscription_id").eq("id", tenant_id).execute()

            if not result.data or not result.data[0].get("stripe_subscription_id"):
                logger.error(f"No active subscription for tenant {tenant_id}")
                return False

            subscription_id = result.data[0]["stripe_subscription_id"]

            # Cancel subscription
            stripe.Subscription.delete(subscription_id)

            # Update tenant
            self.supabase.table("tenants").update({
                "subscription_status": "canceled",
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", tenant_id).execute()

            logger.info(f"✅ Subscription cancelled for tenant {tenant_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel subscription: {e}", exc_info=True)
            return False

    def _handle_invoice_paid(self, invoice):
        """Handle successful invoice payment (recurring)"""
        try:
            customer_id = invoice["customer"]

            # Find tenant by Stripe customer ID
            result = self.supabase.table("tenants").select("*").eq("stripe_customer_id", customer_id).execute()

            if not result.data:
                logger.warning(f"No tenant found for Stripe customer {customer_id}")
                return

            tenant = result.data[0]

            # Record transaction
            self._record_transaction(
                tenant_id=tenant["id"],
                stripe_invoice_id=invoice["id"],
                stripe_charge_id=invoice.get("charge"),
                amount_cents=invoice["amount_paid"],
                currency=invoice["currency"],
                status="succeeded",
                plan_name=tenant.get("plan"),
                billing_period="monthly"  # Could be extracted from subscription
            )

            logger.info(f"✅ Recurring payment processed for {tenant['business_name']}")

        except Exception as e:
            logger.error(f"Failed to handle invoice paid: {e}", exc_info=True)

    def _handle_invoice_failed(self, invoice):
        """Handle failed invoice payment"""
        try:
            customer_id = invoice["customer"]

            # Find tenant
            result = self.supabase.table("tenants").select("*").eq("stripe_customer_id", customer_id).execute()

            if not result.data:
                return

            tenant = result.data[0]

            # Update subscription status
            self.supabase.table("tenants").update({
                "subscription_status": "past_due",
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", tenant["id"]).execute()

            # Record failed transaction
            self._record_transaction(
                tenant_id=tenant["id"],
                stripe_invoice_id=invoice["id"],
                amount_cents=invoice["amount_due"],
                currency=invoice["currency"],
                status="failed",
                failure_message="Payment failed"
            )

            # Notify tenant of payment failure
            try:
                self.email_service.send_trial_expired_email(
                    to=tenant["email"],
                    business_name=tenant["business_name"],
                    upgrade_url=f"{self.public_url}/static/onboarding.html",
                )
            except Exception as email_err:
                logger.warning(f"⚠️ Could not send payment failure email: {email_err}")

            logger.warning(f"⚠️ Payment failed for {tenant['business_name']}")

        except Exception as e:
            logger.error(f"Failed to handle invoice failure: {e}", exc_info=True)

    def _handle_subscription_updated(self, subscription):
        """Handle subscription update (plan change, etc)"""
        try:
            customer_id = subscription["customer"]

            # Find tenant
            result = self.supabase.table("tenants").select("id").eq("stripe_customer_id", customer_id).execute()

            if not result.data:
                return

            tenant_id = result.data[0]["id"]

            # Update tenant
            self.supabase.table("tenants").update({
                "subscription_status": subscription["status"],
                "current_period_end": datetime.fromtimestamp(subscription["current_period_end"]).isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", tenant_id).execute()

            logger.info(f"✅ Subscription updated for tenant {tenant_id}")

        except Exception as e:
            logger.error(f"Failed to handle subscription update: {e}", exc_info=True)

    def _handle_subscription_cancelled(self, subscription):
        """Handle subscription cancellation"""
        try:
            customer_id = subscription["customer"]

            # Find tenant
            result = self.supabase.table("tenants").select("*").eq("stripe_customer_id", customer_id).execute()

            if not result.data:
                return

            tenant = result.data[0]

            # Update tenant
            self.supabase.table("tenants").update({
                "subscription_status": "canceled",
                "stripe_subscription_id": None,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", tenant["id"]).execute()

            logger.info(f"✅ Subscription cancelled for {tenant['business_name']}")

        except Exception as e:
            logger.error(f"Failed to handle subscription cancellation: {e}", exc_info=True)

    def _record_transaction(
        self,
        tenant_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str = None,
        stripe_invoice_id: str = None,
        stripe_charge_id: str = None,
        plan_name: str = None,
        billing_period: str = None,
        failure_message: str = None
    ):
        """Record payment transaction in database"""
        try:
            self.supabase.table("payment_transactions").insert({
                "tenant_id": tenant_id,
                "stripe_payment_intent_id": stripe_payment_intent_id,
                "stripe_invoice_id": stripe_invoice_id,
                "stripe_charge_id": stripe_charge_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "status": status,
                "plan_name": plan_name,
                "billing_period": billing_period,
                "failure_message": failure_message,
                "created_at": datetime.utcnow().isoformat(),
                "paid_at": datetime.utcnow().isoformat() if status == "succeeded" else None
            }).execute()

        except Exception as e:
            logger.error(f"Failed to record transaction: {e}", exc_info=True)


# Global instance
_stripe_service = None


def get_stripe_service() -> StripePaymentService:
    """Get or create Stripe service singleton"""
    global _stripe_service
    if _stripe_service is None:
        _stripe_service = StripePaymentService()
    return _stripe_service
