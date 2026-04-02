from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from app.core.config import Settings
from app.models.schemas import NotificationEvent, Rule

logger = logging.getLogger(__name__)


class DeviationNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    def notify(self, triggered_rules: list[Rule], recipients: list[str] | None = None) -> list[NotificationEvent]:
        recipient_list = recipients or self.settings.default_notification_recipients
        events: list[NotificationEvent] = []

        for rule in triggered_rules:
            if "DEVIATION" not in rule.action and "ESCALATE" not in rule.action and "REJECT" not in rule.action:
                continue
            subject = f"[AP Policy Alert] {rule.action} ({rule.rule_id})"
            body = (
                f"Rule ID: {rule.rule_id}\n"
                f"Source Clause: {rule.source_clause}\n"
                f"Action: {rule.action}\n"
                f"Description: {rule.description}\n"
            )
            for recipient in recipient_list:
                status = self._send_email(recipient, subject, body)
                events.append(
                    NotificationEvent(
                        recipient=recipient,
                        subject=subject,
                        body=body,
                        status=status,
                        rule_id=rule.rule_id,
                    )
                )
        logger.info("Notification flow completed sent=%s", len(events))
        return events

    def _send_email(self, recipient: str, subject: str, body: str) -> str:
        if not self.settings.can_send_email:
            logger.warning("SMTP not configured. Logging email instead recipient=%s subject=%s", recipient, subject)
            return "logged_only"

        message = MIMEText(body)
        message["Subject"] = subject
        message["From"] = self.settings.smtp_from
        message["To"] = recipient

        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as server:
                if self.settings.smtp_use_tls:
                    server.starttls()
                if self.settings.smtp_username and self.settings.smtp_password:
                    server.login(self.settings.smtp_username, self.settings.smtp_password)
                server.sendmail(self.settings.smtp_from, [recipient], message.as_string())
            return "sent"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Email send failed recipient=%s error=%s", recipient, exc)
            return "failed"

