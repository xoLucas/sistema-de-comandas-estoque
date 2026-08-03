from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import aiosmtplib

from app.core.database import async_session
from app.services.settings_service import get_setting


async def _load_smtp_config() -> dict:
    async with async_session() as db:
        return {
            "host": await get_setting(db, "smtp_host", ""),
            "port": int(await get_setting(db, "smtp_port", "587") or 587),
            "user": await get_setting(db, "smtp_user", ""),
            "password": await get_setting(db, "smtp_password", ""),
            "from_addr": await get_setting(db, "smtp_from", ""),
        }


async def send_email_with_attachment(
    to_addr: str,
    subject: str,
    body: str,
    attachment_bytes: bytes | None = None,
    attachment_filename: str = "relatorio.pdf",
) -> dict:
    config = await _load_smtp_config()

    if not config["host"] or not config["from_addr"] or not to_addr:
        return {"success": False, "error": "Configuração de email incompleta"}

    msg = MIMEMultipart()
    msg["From"] = config["from_addr"]
    msg["To"] = to_addr
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_bytes:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

    try:
        await aiosmtplib.send(
            msg,
            hostname=config["host"],
            port=config["port"],
            username=config["user"] or None,
            password=config["password"] or None,
            start_tls=True if config["port"] == 587 else False,
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
