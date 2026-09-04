"""EmailProvider interface plus the development provider (Mailpit over SMTP).

The project runs end to end locally with no external email service and no API key.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from app.common.logging import get_logger
from app.config.settings import settings

log = get_logger("email")


@dataclass(slots=True)
class Email:
    to: str
    subject: str
    body: str


class EmailProvider(Protocol):
    def send(self, email: Email) -> None: ...


@dataclass
class DevelopmentEmailProvider:
    """Writes to Mailpit's SMTP port.  If Mailpit is absent, the message is captured
    in-memory and logged so the flow still completes -- never a hard failure that
    blocks registration in a local environment."""

    host: str = settings.SMTP_HOST
    port: int = settings.SMTP_PORT
    sender: str = settings.EMAIL_FROM
    outbox: list[Email] = field(default_factory=list)

    def send(self, email: Email) -> None:
        self.outbox.append(email)
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=5) as smtp:
                smtp.send_message(message)
            delivered = "mailpit"
        except OSError as exc:
            delivered = f"captured (smtp unavailable: {type(exc).__name__})"
        # The recipient address is a masked field (I11); only the subject is logged.
        log.info("email sent", extra={"subject": email.subject, "transport": delivered})


class MemoryEmailProvider(DevelopmentEmailProvider):
    """Used by tests: never opens a socket."""

    def send(self, email: Email) -> None:
        self.outbox.append(email)
        log.info("email captured", extra={"subject": email.subject, "transport": "memory"})


_provider: EmailProvider | None = None


def get_email_provider() -> EmailProvider:
    global _provider
    if _provider is None:
        # Only one provider exists on purpose: the project must run end to end
        # with no external email service and no API key.  A real SMTP relay is a
        # host and port change on DevelopmentEmailProvider, not a new class.
        _provider = DevelopmentEmailProvider()
    return _provider


def set_email_provider(provider: EmailProvider) -> None:
    global _provider
    _provider = provider


# ── Templates (spec 23) ─────────────────────────────────────────────────────
TEMPLATES = {
    "verify_email": (
        "Verify your Aegis email address",
        "Hello {name},\n\nConfirm your email address to start creating and funding deals:\n\n"
        "{link}\n\nThe link expires in 24 hours.\n\n-- Aegis",
    ),
    "password_reset": (
        "Reset your Aegis password",
        "Hello {name},\n\nUse this single-use link to choose a new password:\n\n{link}\n\n"
        "It expires in 30 minutes. If you did not request this, ignore this email.\n\n-- Aegis",
    ),
    "org_invitation": (
        "You have been invited to an Aegis organization",
        "Hello,\n\n{inviter} invited you to join {org} as {role}.\n\nAccept the invitation:\n\n"
        "{link}\n\nThe invitation expires in 7 days.\n\n-- Aegis",
    ),
    "human_review_required": (
        "Human review required on {deal}",
        "The verifier escalated milestone {milestone} on {deal}.\n\n"
        "What it could not verify:\n{unverifiable}\n\nReview it here:\n{link}\n\n-- Aegis",
    ),
    "dispute_raised": (
        "A dispute was raised on {deal}",
        "A dispute was raised on milestone {milestone} of {deal}.\n\nClaim:\n{claim}\n\n{link}\n\n-- Aegis",
    ),
    "settlement_completed": (
        "Settlement completed on {deal}",
        "{amount} was {direction} on milestone {milestone} of {deal}.\n\n{link}\n\n-- Aegis",
    ),
}


def render(template: str, to: str, **kwargs: object) -> Email:
    subject, body = TEMPLATES[template]
    return Email(to=to, subject=subject.format(**kwargs), body=body.format(**kwargs))
