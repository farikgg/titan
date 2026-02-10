"""
Для асинхронной работы с почтой будем использовать библиотеку aioimaplib (для чтения) и aiosmtplib (для отправки КП).
"""
import email, logging
from aioimaplib import aioimaplib

from email.header import decode_header
from typing import List, Dict, Any

from src.app.config import settings

logger = logging.getLogger(__name__)


class EmailParser:
    def __init__(self):
        self.host = settings.IMAP_HOST
        self.port = settings.IMAP_PORT
        self.user = settings.EMAIL_USER
        self.password = settings.EMAIL_APP_PASSWORD

    async def fetch_last_message(self, limit: int = 10):
        """
        идет подключение к почте
        Загружает последние письма из INBOX
        Возвращает список словарей
        {
            message_ids,
            subject,
            from,
            body,
            attachments
        }
        """
        logger.info(f"DEBUG: Пробую войти как {self.user} с паролем, заканчивающимся на ...{self.password[-4:]}")
        imap_client = aioimaplib.IMAP4_SSL(self.host, self.port)
        await imap_client.wait_hello_from_server()

        try:
            # регаемся на почту и выбираем откуда парсить сообщения
            resp = await imap_client.login(self.user, self.password)
            logger.info(f"ответ от сервера на логин: {resp}")

            if resp.result != "OK":
                logger.error(f"авторизация не удалась, {resp}")
                return []

            await imap_client.select("INBOX")

            _, data = await imap_client.search("ALL")
            msg_ids = data[0].split()[-limit:]

            email_data = []

            for m_id in msg_ids:
                _, msg_data = await imap_client.fetch(m_id, "(RFC822)")
                raw_email = msg_data[1]

                # идет парсинг писем
                msg = email.message_from_bytes(raw_email)
                parsed_content = self._parse_message(msg)
                email_data.append(parsed_content)

            return email_data

        except Exception as e:
            logger.error(f"Ошибка с почтой: {e}")
            return []
        finally:
            # выходим с почты после того как сделали парсинг, чтобы не забанило
            try:
                await imap_client.logout()
            except Exception:
                pass

    def _parse_message(self, msg: email.message.Message) -> Dict[str, Any]:
        subject = self._decode_header(msg.get("Subject"))
        message_id = msg.get("Message-ID")

        result = {
            "message_ids": message_id,
            "subject": subject,
            "from": msg.get("From"),
            "body": "",
            "attachments": [],
        }

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition"))

                try:
                    if content_type == "text/plain" and "attachment" not in disposition:
                        charset = part.get_content_charset() or "utf-8"
                        result["body"] += part.get_payload(decode=True).decode(
                            charset, errors="replace"
                        )

                    elif "attachment" in disposition:
                        filename = part.get_filename()
                        if filename:
                            filename = self._decode_header(filename)
                            result["attachments"].append(
                                {
                                    "name": filename,
                                    "content": part.get_payload(decode=True),
                                    "mime_type": content_type,
                                }
                            )
                except Exception as e:
                    logger.warning(f"Failed to parse part: {e}")

        else:
            result["body"] = msg.get_payload(decode=True).decode(errors="ignore")

        return result

    def _decode_header(self, value: str | None) -> str:
        """
        Декодирует MIME-заголовки типа =?UTF-8?B?...
        """
        if not value:
            return ""
        decoded_parts = decode_header(value)
        parts = []


        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                parts.append(
                    content.decode(encoding or "utf-8", errors="ignore")
                )
            else:
                parts.append(str(content))

        return "".join(parts)
