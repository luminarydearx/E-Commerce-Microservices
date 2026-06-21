"""Notification business logic — async multi-channel dispatcher."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Environment, FileSystemLoader, select_autoescape
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger("notification_service.service")

# Jinja2 template environment
env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=True,
)


class NotificationService:
    """Dispatch notifications to multiple channels (email, push, in-app)."""

    async def send(self, payload: dict[str, Any]) -> None:
        channel = payload.get("channel", "email")
        try:
            if channel == "email":
                await self._send_email(payload)
            elif channel == "push":
                await self._send_push(payload)
            elif channel == "in_app":
                await self._send_in_app(payload)
            else:
                logger.warning("unknown channel", extra={"channel": channel})
        except Exception as e:
            logger.error(
                "notification send failed",
                exc_info=True,
                extra={"channel": channel, "error": str(e), "payload": payload},
            )
            # In production: write to retry queue / DLQ

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _send_email(self, payload: dict[str, Any]) -> None:
        to = payload.get("to")
        if not to:
            raise ValueError("missing 'to' field")
        template_name = payload.get("template", "default.html")
        context = payload.get("context", {})

        try:
            template = env.get_template(template_name)
            html_body = await template.render_async(**context)
        except Exception as e:
            logger.warning("template not found, using plain text", extra={"error": str(e)})
            html_body = payload.get("body", "")

        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = payload.get("subject", "Notification")
        msg.attach(MIMEText(payload.get("text", ""), "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if not settings.SMTP_HOST:
            logger.info("dev mode: email not sent", extra={"to": to, "subject": msg["Subject"]})
            return

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info("email sent", extra={"to": to, "subject": msg["Subject"]})

    async def _send_push(self, payload: dict[str, Any]) -> None:
        # Stub: integrate with FCM/APNs
        logger.info("push notification (stub)", extra={"user_id": payload.get("user_id")})

    async def _send_in_app(self, payload: dict[str, Any]) -> None:
        # Stub: write to notification table for retrieval via API
        logger.info("in-app notification (stub)", extra={"user_id": payload.get("user_id")})

    # ===== Templates for specific events =====

    async def on_user_registered(self, event: dict[str, Any]) -> None:
        user = event.get("resource", {}).get("after", {})
        await self.send({
            "channel": "email",
            "to": user.get("email"),
            "subject": "Welcome to E-Commerce!",
            "template": "welcome.html",
            "context": {"name": user.get("email", "")},
        })

    async def on_order_created(self, event: dict[str, Any]) -> None:
        # Buyer email
        await self.send({
            "channel": "email",
            "to": event.get("buyer_email"),
            "subject": f"Order {event.get('resource', {}).get('id')} created",
            "template": "order_created.html",
            "context": {"order_id": event.get("resource", {}).get("id")},
        })

    async def on_payment_succeeded(self, event: dict[str, Any]) -> None:
        await self.send({
            "channel": "email",
            "to": event.get("buyer_email"),
            "subject": "Payment received",
            "template": "payment_success.html",
            "context": {"payment_id": event.get("resource", {}).get("id")},
        })

    async def on_payment_failed(self, event: dict[str, Any]) -> None:
        await self.send({
            "channel": "email",
            "to": event.get("buyer_email"),
            "subject": "Payment failed",
            "template": "payment_failed.html",
            "context": {"payment_id": event.get("resource", {}).get("id")},
        })
