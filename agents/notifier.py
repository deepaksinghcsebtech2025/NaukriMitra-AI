"""Telegram and Gmail notifications for applications and summaries."""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from agents.base import BaseAgent


class NotifierAgent(BaseAgent):
    """Sends Markdown Telegram messages and HTML email summaries."""

    async def send_telegram(self, message: str) -> bool:
        """POST to Telegram Bot API; swallow errors."""

        token = self.settings.telegram_bot_token
        chat_id = self.settings.telegram_chat_id
        if not token or not chat_id:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                )
                return resp.status_code == 200
        except Exception as exc:
            await self.log(f"Telegram error: {exc}", "warning")
            return False

    async def send_email(self, subject: str, body_html: str) -> bool:
        """Send HTML email via Gmail SMTP (app password)."""

        email = self.settings.smtp_email
        password = self.settings.smtp_app_password
        if not email or not password:
            return False

        def _send() -> bool:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = email
            msg["To"] = email
            msg.attach(MIMEText(body_html, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(email, password)
                server.sendmail(email, email, msg.as_string())
            return True

        try:
            return await asyncio.to_thread(_send)
        except Exception as exc:
            await self.log(f"Email error: {exc}", "warning")
            return False

    async def notify_application(self, job: dict, application: dict, status: str) -> None:
        """Notify on application outcome."""

        emoji = {"APPLIED": "✅", "FAILED": "❌", "MANUAL_REVIEW": "⚠️", "SUBMITTED": "📨"}
        e = emoji.get(status, "ℹ️")
        msg = (
            f"{e} *{status}*\n"
            f"*{job.get('title', 'Unknown')}* at *{job.get('company', 'Unknown')}*\n"
            f"📍 {job.get('location', 'N/A')} | 🎯 Match: {job.get('match_score', 0)}%"
        )
        await self.send_telegram(msg)

    async def send_daily_summary(self) -> None:
        """Push pipeline stats to Telegram and email."""

        from agents.tracker import TrackerAgent

        stats = await TrackerAgent().get_pipeline_stats()
        msg = (
            f"📊 *Ultra Job Agent — Daily Summary*\n\n"
            f"🔍 Total jobs: {stats.get('total_jobs', 0)}\n"
            f"✅ Applied today: {stats.get('today_applied', 0)}\n"
            f"📅 This week: {stats.get('week_applied', 0)}\n"
            f"🎤 Interviews: {stats.get('INTERVIEW', 0)}\n"
            f"💼 Offers: {stats.get('OFFER', 0)}\n"
            f"📈 Avg match score: {stats.get('avg_match_score', 0)}%\n"
            f"⚠️ Manual review: {stats.get('MANUAL_REVIEW', 0)}"
        )
        await self.send_telegram(msg)
        await self.send_email("Ultra Job Agent — Daily Summary", f"<pre>{msg}</pre>")

    async def run(self) -> dict:
        """Manual trigger for daily summary."""

        await self.send_daily_summary()
        return {"sent": True}
