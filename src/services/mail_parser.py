"""
Для асинхронной работы с почтой будем использовать библиотеку aioimaplib (для чтения) и aiosmtplib (для отправки КП).
"""
import email, logging
from aioimaplib import aioimaplib

from email.header import decode_header

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
        """
        logger.info(f"DEBUG: Пробую войти как {self.user} с паролем, заканчивающимся на ...{self.password[-4:]}")
        imap_client = aioimaplib.IMAP4_SSL(self.host, self.port)
        await imap_client.wait_hello_from_server()

        try:
            # регаемся на почту и выбираем откуда парсить сообщения
            # await imap_client.login(self.user, self.password)
            resp = await imap_client.login(self.user, self.password)
            logger.info(f"ответ от сервера на логин: {resp}")

            if resp.result != "OK":
                logger.error(f"авторизация не удалась, {resp}")
                return []

            await imap_client.select("INBOX")

            obj, data = await imap_client.search("FROM fuchs") # тут можно выбрать ALL или FROM fuchs
            msg_ids = data[0].split()[-limit:]

            email_data = []

            for m_id in msg_ids:
                obj, msg_data = await imap_client.fetch(m_id, "(RFC822)")
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
            except:
                pass

    def _parse_message(self, msg):
        """
        Разбирает MIME-структуру письма на текст и вложения.
        """
        subject = self._decode_header(msg.get("Subject"))
        res = {
            'message_ids': msg.get('Message-ID'),
            'subject': subject,
            'from': msg.get('From'),
            'body': '',
            'attachments': []
        }

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Извлекаем текст
                charset = part.get_content_charset()
                try:
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        content = part.get_payload(decode=True).decode(charset, errors='replace')
                        res["body"] += content

                    # Извлекаем вложения
                    elif "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            # Декодируем имя файла, если оно зашифровано
                            filename = str(email.header.make_header(email.header.decode_header(filename)))
                            res["attachments"].append({
                                "name": filename,
                                "content": part.get_payload(decode=True),
                                "mime_type": content_type
                            })
                except Exception as e:
                    res["body"] += part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            res["body"] = msg.get_payload(decode=True).decode(errors='ignore')

        return res

    def _decode_header(self, value: str) -> str:
        """
        Декодирует MIME-заголовки типа =?UTF-8?B?...
        """
        if not value:
            return ""

        try:
            decoded_parts = []
            parts = decode_header(value)
            for content, encoding in parts:
                if isinstance(content, bytes):
                    decoded_parts.append(content.decode(encoding or "utf-8", errors="ignore"))
                else:
                    decoded_parts.append(str(content))
            return "".join(decoded_parts)
        except Exception as e:
            logger.error(f"Ошибка decoding: {e}")
            return value
