import base64
import httpx
from typing import List

from src.core.graph_auth import GraphAuth


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookClient:
    def __init__(self, auth: GraphAuth, mailbox: str | None = None, folder_name: str = "inbox"):
        """
        Args:
            auth: GraphAuth instance
            mailbox: Email address (один аккаунт, например "testAI@tpgt-titan.com").
                     If None, uses default from settings or "testAI@tpgt-titan.com"
            folder_name: Название папки (например "Inbox" или "Requests"). 
                         Если не "inbox", скрипт найдет её ID по displayName.
        """
        self.auth = auth
        self.mailbox = mailbox
        self.folder_name = folder_name.lower() if folder_name.lower() == "inbox" else folder_name

    async def _headers(self):
        token = await self.auth.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _get_folder_id(self, client: httpx.AsyncClient, mailbox: str) -> str:
        """Получает ID папки по её displayName (если это не well-known 'inbox')"""
        if self.folder_name == "inbox":
            return "inbox"
            
        url_folders = f"{GRAPH_BASE}/users/{mailbox}/mailFolders"
        resp = await client.get(url_folders, headers=await self._headers())
        resp.raise_for_status()
        
        folders = resp.json().get("value", [])
        for f in folders:
            if f.get("displayName", "").lower() == self.folder_name.lower():
                return f.get("id")
                
        # Фоллбэк, если папка не найдена
        import logging
        logging.getLogger(__name__).warning("Folder '%s' not found for %s, falling back to inbox", self.folder_name, mailbox)
        return "inbox"

    async def fetch_last_messages(self, limit: int = 50) -> List[dict]:
        """
        Получает последние письма из указанной папки.
        """
        mailbox = self.mailbox or "testAI@tpgt-titan.com"

        async with httpx.AsyncClient(timeout=30) as client:
            folder_id = await self._get_folder_id(client, mailbox)
            
            url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders/{folder_id}/messages"
            params = {
                "$top": limit,
                "$orderby": "receivedDateTime DESC",
                "$expand": "attachments",
            }
            
            resp = await client.get(url, headers=await self._headers(), params=params)
            resp.raise_for_status()
            return resp.json().get("value", [])

    @staticmethod
    def parse_attachments(raw_attachments: list) -> list[dict]:
        """
        Приводит Graph attachments к формату:
        { name, content, mime_type }
        """
        parsed = []

        for att in raw_attachments or []:
            if "contentBytes" not in att:
                continue

            parsed.append({
                "name": att["name"],
                "mime_type": att.get("contentType"),
                "content": base64.b64decode(att["contentBytes"]),
            })

        return parsed

    async def send_email(self, to_email: str, subject: str, body: str):
        """
        Отправляет письмо через Microsoft Graph API.
        """
        mailbox = self.mailbox or "testAI@tpgt-titan.com"
        url = f"{GRAPH_BASE}/users/{mailbox}/sendMail"

        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email,
                        }
                    }
                ],
            },
            "saveToSentItems": "true",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=await self._headers(), json=payload)
            resp.raise_for_status()
            return True
