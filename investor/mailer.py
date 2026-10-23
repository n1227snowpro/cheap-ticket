"""Outgoing e-mail over SMTP. Without SMTP settings, messages are logged (dev mode)."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

import config

logger = logging.getLogger(__name__)

# Last messages, for tests and local debugging when SMTP is not configured.
outbox: list = []


def send(to: str, subject: str, text: str) -> bool:
    cfg = config.load()
    msg = EmailMessage()
    msg["From"] = cfg["smtp_from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if not cfg.get("smtp_host"):
        outbox.append({"to": to, "subject": subject, "text": text})
        del outbox[:-50]
        logger.info(f"[mail not configured] To {to}: {subject}\n{text}")
        return False
    try:
        port = int(cfg.get("smtp_port") or 587)
        if port == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_host"], port, context=ssl.create_default_context(), timeout=20)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], port, timeout=20)
            server.starttls(context=ssl.create_default_context())
        with server:
            if cfg.get("smtp_user"):
                server.login(cfg["smtp_user"], cfg["smtp_password"])
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"E-mail to {to} failed: {e}")
        return False
