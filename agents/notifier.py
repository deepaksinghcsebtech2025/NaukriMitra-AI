"""Telegram and Gmail notifications for applications and summaries."""

from __future__ import annotations

import asyncio
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from agents.base import BaseAgent


class NotifierAgent(BaseAgent):
    """Sends Markdown Telegram messages and HTML email summaries."""

    # -----------------------------------------------------------------------
    # Telegram
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Email — now with a proper HTML template
    # -----------------------------------------------------------------------

    async def send_email(self, subject: str, body_html: str) -> bool:
        """Send HTML email via Gmail SMTP (app password)."""
        email = self.settings.smtp_email
        password = self.settings.smtp_app_password
        if not email or not password:
            return False

        def _send() -> bool:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Ultra Job Agent <{email}>"
            msg["To"] = email
            msg.attach(MIMEText(body_html, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                server.login(email, password)
                server.sendmail(email, email, msg.as_string())
            return True

        try:
            return await asyncio.to_thread(_send)
        except Exception as exc:
            await self.log(f"Email error: {exc}", "warning")
            return False

    def _build_summary_html(self, stats: dict) -> str:
        """Render a clean HTML email for daily summary."""
        today_str = date.today().strftime("%A, %d %B %Y")

        def stat_row(label: str, value, color: str = "#1a1a2e") -> str:
            return f"""
            <tr>
              <td style="padding:8px 16px;color:#555;font-size:14px;">{label}</td>
              <td style="padding:8px 16px;font-weight:bold;font-size:15px;color:{color};">{value}</td>
            </tr>"""

        rows = (
            stat_row("Total jobs discovered", stats.get("total_jobs", 0))
            + stat_row("Applied today", stats.get("today_applied", 0), "#2563eb")
            + stat_row("Applied this week", stats.get("week_applied", 0), "#2563eb")
            + stat_row("Interviews", stats.get("INTERVIEW", 0), "#16a34a")
            + stat_row("Offers", stats.get("OFFER", 0), "#15803d")
            + stat_row("Avg match score", f"{stats.get('avg_match_score', 0)}%")
            + stat_row("Manual review needed", stats.get("MANUAL_REVIEW", 0), "#d97706")
            + stat_row("Rejected / Failed", stats.get("FAILED", 0), "#dc2626")
        )

        return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1a1a2e 0%,#2563eb 100%);
                     padding:28px 32px;color:#fff;">
            <div style="font-size:22px;font-weight:bold;">Ultra Job Agent</div>
            <div style="font-size:13px;opacity:.8;margin-top:4px;">Daily Summary · {today_str}</div>
          </td>
        </tr>
        <!-- Stats table -->
        <tr><td>
          <table width="100%" cellpadding="0" cellspacing="0">
            {rows}
          </table>
        </td></tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:16px 32px;
                     font-size:12px;color:#94a3b8;text-align:center;border-top:1px solid #e2e8f0;">
            Ultra Job Agent · Automated by AI
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    # -----------------------------------------------------------------------
    # Notification helpers
    # -----------------------------------------------------------------------

    async def notify_application(self, job: dict, application: dict, status: str) -> None:
        """Notify on individual application outcome (Telegram only — keep concise)."""
        emoji = {
            "APPLIED": "✅", "FAILED": "❌", "MANUAL_REVIEW": "⚠️",
            "SUBMITTED": "📨", "INTERVIEW": "🎤", "OFFER": "🎉",
        }
        e = emoji.get(status, "ℹ️")
        salary = ""
        sal_min = job.get("salary_min")
        if sal_min:
            sal_max = job.get("salary_max", sal_min)
            salary = f"\n💰 ₹{sal_min:,} – ₹{sal_max:,}"

        msg = (
            f"{e} *{status}*\n"
            f"*{job.get('title', 'Unknown')}* at *{job.get('company', 'Unknown')}*\n"
            f"📍 {job.get('location', 'N/A')} | 🎯 Match: {job.get('match_score', 0)}%"
            f"{salary}"
        )
        await self.send_telegram(msg)

    async def send_daily_summary(self) -> None:
        """Push pipeline stats to Telegram and email."""
        from agents.tracker import TrackerAgent

        stats = await TrackerAgent().get_pipeline_stats()

        # Telegram message (Markdown)
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

        # Rich HTML email
        html = self._build_summary_html(stats)
        today_str = date.today().strftime("%d %b %Y")
        await self.send_email(f"Ultra Job Agent — Daily Summary {today_str}", html)

    async def run(self) -> dict:
        """Manual trigger for daily summary."""
        await self.send_daily_summary()
        return {"sent": True}
