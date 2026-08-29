"""
Knowledge Loader for Bijou AI
==============================

Loads W3J-specific knowledge, system prompts, and interaction logic.

Author: W3J Bijou AI
Version: 1.0.0
"""

import os
import time
from pathlib import Path
from typing import Dict, Optional


class KnowledgeLoader:
    """
    Loads and manages W3J Consulting knowledge base for Bijou AI.
    """

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize knowledge loader.

        Args:
            base_path: Base directory path (defaults to src/core)
        """
        if base_path is None:
            # Get the directory where this file is located
            self.base_path = Path(__file__).parent
        else:
            self.base_path = Path(base_path)

        self.system_prompt = None
        self.knowledge_base = None
        self.last_loaded = None

    def load_system_prompt(self) -> str:
        """
        Load the canonical Bijou AI system prompt.

        This is the MANGGLISH sales persona, mirrored at
        packages/landing/api/chat.js (the Vercel landing widget).
        Edit both files together when the persona changes.

        Returns:
            str: Complete system prompt with Bijou AI knowledge
        """
        prompt_file = self.base_path / "bijou_system_prompt.txt"

        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                self.system_prompt = f.read()
                self.last_loaded = time.time()
                print(
                    f"[OK] Loaded Bijou AI system prompt ({len(self.system_prompt)} chars)"
                )
                return self.system_prompt
        except FileNotFoundError:
            print(f"[WARN] System prompt not found at {prompt_file}")
            return self._get_fallback_prompt()
        except Exception as e:
            print(f"[ERROR] Failed to load system prompt: {e}")
            return self._get_fallback_prompt()

    def _get_fallback_prompt(self) -> str:
        """
        Fallback system prompt if `bijou_system_prompt.txt` is not found.

        Intentionally minimal — just enough to keep the bot in the canonical
        Bijou AI voice. The full persona is loaded from disk on app start;
        if you see this in production, restore the canonical file.

        Returns:
            str: Basic Bijou AI prompt (Manglish)
        """
        return """You are Bijou, an AI Digital Employee for Malaysian businesses built by Bijou AI.

Reply in Manglish always. Be friendly, helpful, and transparent about being an AI.

Plan: PRO at RM299/month. 30-day money-back guarantee. No setup fee.
Trial: 14 days free, no card required.

Contact: jewel@mybijou.xyz | wa.me/60174106981
Website: https://mybijou.xyz
"""

    def get_interaction_rules(self) -> Dict[str, any]:
        """
        Get interaction logic rules for smart response behavior.

        Returns:
            Dict: Configuration for when/how to respond
        """
        return {
            # When to respond
            "respond_if_user_inactive_seconds": 300,  # 5 minutes
            "respond_if_urgent_keywords": [
                "urgent",
                "asap",
                "emergency",
                "help",
                "quickly",
                "important",
            ],
            "respond_if_new_contact": True,
            "respond_if_direct_question": True,
            # When to stay silent
            "silent_if_user_active_seconds": 120,  # 2 minutes
            "silent_if_casual_messages": ["ok", "thanks", "k", "👍", "😊"],
            "silent_if_user_already_responded": True,
            # Response timing (human-like delays)
            "base_delay_seconds": 3,
            "reading_speed_seconds_per_word": 0.5,
            "thinking_time_simple_seconds": (2, 5),  # min, max
            "thinking_time_complex_seconds": (5, 15),  # min, max
            "max_delay_seconds": 30,
            # Old message handling
            "old_message_respond_threshold_minutes": 10,
            "old_message_followup_threshold_minutes": 60,
            "old_message_ignore_threshold_minutes": 120,
            # User activity detection
            "user_activity_window_seconds": 300,  # 5 minutes
            "wait_for_user_response_seconds": 30,
            # Introduction patterns
            "introduce_on_first_contact": True,
            "introduce_when_stepping_in": True,
        }

    def get_response_templates(self) -> Dict[str, str]:
        """
        Get response templates for common scenarios.

        Returns:
            Dict: Templates keyed by scenario name
        """
        return {
            "first_contact": """Hi! I'm Bijou, Jewel's AI assistant for W3J Consulting.

I help manage inquiries about our services when Jewel is busy or offline.

How can I help you today?""",
            "returning_contact": "Hi again! Bijou here. What can I help you with?",
            "stepping_in": """Hi! I notice you might need help with this. I'm Bijou, Jewel's AI assistant. Would you like me to assist while Jewel is busy?""",
            "escalate_to_jewel": """I'll connect you with Jewel directly for this. He'll get back to you within {timeframe}.

In the meantime, here's his email if you'd like to reach out: gwadmin@w3jdev.com""",
            "out_of_hours": """I've noted your message. Jewel typically responds within 2-4 hours during business hours (Monday-Friday, 9 AM - 6 PM MYT).

Is there anything I can help you with in the meantime?""",
            "service_inquiry": """W3J specializes in {area}. We've built {product} which helps with {problem}.

For example, {example}.

Would you like to schedule a call with Jewel to discuss your specific situation?""",
            "pricing_inquiry": """Our pricing varies based on scope and requirements. Generally:

- Consultation: RM150/hour
- Small projects: Starting at RM5,000
- Custom SaaS solutions: RM10,000+
- Monthly retainers: Custom packages available

I'd recommend a free 30-minute consultation with Jewel to discuss your needs and get an accurate quote. Would that work for you?""",
        }

    def get_w3j_products(self) -> Dict[str, Dict[str, str]]:
        """
        Get W3J product portfolio information.

        Returns:
            Dict: Product information keyed by product name
        """
        return {
            "interviewos": {
                "name": "InterviewOS",
                "url": "https://interviewos.w3jdev.com",
                "description": "AI-powered interview coach with real-time feedback",
                "status": "Live with 100+ users",
                "metric": "8.5/10 average performance improvement",
                "revenue_model": "Freemium",
            },
            "punchclock": {
                "name": "PUNCHCLOCK",
                "url": "Coming soon",
                "description": "Neo-Brutalist HR OS for Malaysian SMEs",
                "features": "Biometric attendance, EPF/SOCSO compliance, AI copilot",
                "pricing": "RM29-99/month per company",
                "target": "200k+ Malaysian SMBs",
            },
            "digibiz": {
                "name": "DIGIBIZ COPILOT",
                "url": "Coming soon",
                "description": "Agentic AI for Google Workspace automation",
                "integration": "Gmail, Sheets, Docs, Drive, Forms, Calendar",
                "pricing": "RM499/month (Starter) to Enterprise custom",
            },
            "bijou": {
                "name": "Bijou AI",
                "url": "You're talking to me!",
                "description": "Bypassing Bureaucracy Through Intelligent Systems",
                "specialty": "Malaysian regulatory expertise (LHDN, SSM, labor law)",
                "languages": "Malay-first, English, Mandarin",
                "pricing": "Freemium → RM19/month → RM99/month",
            },
            "menumate": {
                "name": "MenuMate",
                "url": "Coming soon",
                "description": "Restaurant automation and menu management",
                "status": "MVP complete, seeking partnerships",
            },
            "artisanai": {
                "name": "ArtisanAI",
                "url": "Coming soon",
                "description": "AI-powered resume builder for job seekers",
                "status": "Live, 50+ users helped land better roles",
            },
            "smart_attendance": {
                "name": "Smart Attendance",
                "url": "Coming soon",
                "description": "Biometric + AI attendance tracking for Malaysian SMBs",
                "status": "Deployed in pilot customers",
            },
            "istana": {
                "name": "Istana Home Decor",
                "url": "Client project",
                "description": "Interior design studio automation",
                "status": "Active delivery",
            },
        }

    def get_jewel_info(self) -> Dict[str, any]:
        """
        Get information about Jewel (Muhammad Nurunnabi).

        Returns:
            Dict: Jewel's bio, contact, expertise
        """
        return {
            "name": "Muhammad Nurunnabi",
            "nickname": "Jewel",
            "location": "Subang Jaya, Selangor, Malaysia",
            "origin": "Rural Bangladesh → Kuala Lumpur",
            "philosophy": "Automation is for the underserved",
            "defining_moment": "Saved his mother's life using AI-powered automation",
            "contact": {
                "email": "gwadmin@w3jdev.com",
                "website": "https://w3jdev.com",
                "portfolio": "https://portfolio.w3jdev.com",
                "interviewos": "https://interviewos.w3jdev.com",
                "github": "https://github.com/w3jdev",
                "linkedin": "https://linkedin.com/in/w3jdev",
            },
            "expertise": [
                "AI & Automation (LLM integration, agentic systems, TRACE framework)",
                "Full-Stack Development (Node.js, Python, Go, React, Next.js)",
                "Google Workspace Ecosystem (Apps Script expert)",
                "Cloud (GCP, Docker, serverless architecture)",
                "Blockchain & DeFi",
                "F&B Digital Transformation",
            ],
            "current_roles": [
                "Full Stack Developer Consultant at Neurones IT Asia",
                "Founder/Product Lead at W3J Consulting (16h/week ops)",
                "Actively seeking Senior Full-Stack AI Engineer roles (RM15-25k/month)",
            ],
        }

    def enhance_prompt_with_context(
        self, base_prompt: str, user_phone: str, conversation_history: list
    ) -> str:
        """
        Enhance system prompt with conversation context.

        Args:
            base_prompt: Base system prompt
            user_phone: User's phone number
            conversation_history: Recent conversation history

        Returns:
            str: Enhanced prompt with context
        """
        # Determine if this is first contact
        is_first_contact = len(conversation_history) == 0

        # Add context to prompt
        context_addition = f"""

## CURRENT CONVERSATION CONTEXT

User: {user_phone}
Contact Type: {"New contact (first time)" if is_first_contact else "Returning user"}
Conversation History: {len(conversation_history)} previous messages

"""

        if conversation_history:
            recent_messages = conversation_history[-3:]  # Last 3 messages
            context_addition += "Recent Messages:\n"
            for msg in recent_messages:
                role = "User" if msg.get("from_me", False) else "Bijou"
                text = msg.get("text", "")[:100]  # Truncate long messages
                context_addition += f"- {role}: {text}\n"

        context_addition += """
Remember: Use this context to provide coherent, contextually-aware responses.
Don't repeat information you've already shared in this conversation.
"""

        return base_prompt + context_addition


# Singleton instance
_knowledge_loader = None


def get_knowledge_loader() -> KnowledgeLoader:
    """
    Get singleton knowledge loader instance.

    Returns:
        KnowledgeLoader: Shared knowledge loader
    """
    global _knowledge_loader
    if _knowledge_loader is None:
        _knowledge_loader = KnowledgeLoader()
    return _knowledge_loader
