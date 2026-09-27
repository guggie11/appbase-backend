"""Email sending utilities for auth flows."""
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings


async def send_verification_email(to_email: str, token: str) -> None:
    link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    body = f"""
Halo,

Klik link berikut untuk memverifikasi email Anda:
{link}

Link ini berlaku selama 24 jam.

Terima kasih.
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Verifikasi Email Anda"
    msg["From"] = "noreply@appbase.local"
    msg["To"] = to_email

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
    )


async def send_reset_email(to_email: str, token: str) -> None:
    link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    body = f"""
Halo,

Klik link berikut untuk mereset password Anda:
{link}

Link ini berlaku selama 1 jam.

Jika Anda tidak meminta reset password, abaikan email ini.
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Reset Password"
    msg["From"] = "noreply@appbase.local"
    msg["To"] = to_email

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
    )
