"""
Для асинхронной работы с почтой будем использовать библиотеку aioimaplib (для чтения) и aiosmtplib (для отправки КП).
"""
import email, logging
from aioimaplib import aioimaplib

from src.app.config import settings

logger = logging.getLogger(__name__)


class EmailParser:
    def __init__(self):
        self.host = settings.IMAP_HOST
        self.port = settings.IMAP_PORT
        self.user = settings.EMAIL_USER
        self.password = settings.EMAIL_PASSWORD

    async def fetch_last_message(self, limit: int = 10):
        """
        идет подключение к почте
        """
        imap_client = aioimaplib.IMAP4(self.host, self.port)
        await imap_client.wait_hello_from_server()

        try:
            # регаемся на почту и выбираем откуда парсить сообщения
            await imap_client.login(self.user, self.password)
            await imap_client.select("INBOX")

            obj, data = await imap_client.search("FROM fuchs") # тут можно выбрать ALL или FROM fuchs
            msg_ids = data[0].split()[-limit:]

            email_data = []

            for m_id in msg_ids:
                obj, msg_data = await imap_client.fetch(m_id, "(RFC822)")
                raw_email = msg_data[1]

                # идет парсинг писем
                msg = email.message_from_bytes(raw_email)
                parsed_content = self._parce_message(msg)
                email_data.append(parsed_content)

            return email_data

        except Exception as e:
            logger.error(f"Ошибка с почтой: {e}")
        finally:
            # выходим с почты после того как сделали парсинг, чтобы не забанило
            await imap_client.logout()

    def _parce_message(self, msg):
        """
        Разбирает MIME-структуру письма на текст и вложения.
        """
        res = {
            'subject': str(email.header.make_header(email.header.decode_header(msg['Subject']))),
            'from': msg['From'],
            'body': '',
            'attachments': []
        }

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Извлекаем текст
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    res["body"] += part.get_payload(decode=True).decode(errors='ignore')

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
        else:
            res["body"] = msg.get_payload(decode=True).decode(errors='ignore')

        return res