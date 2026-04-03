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

    async def send_email(self, to_email: str, subject: str, body: str) -> dict:
        """
        Отправляет письмо через Microsoft Graph API в два этапа:
        создание черновика (для получения ID) и его отправка.
        Возвращает {'id': ..., 'conversationId': ...}
        """
        mailbox = self.mailbox or "testAI@tpgt-titan.com"
        draft_url = f"{GRAPH_BASE}/users/{mailbox}/messages"

        payload = {
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
        }

        async with httpx.AsyncClient(timeout=30) as client:
            headers = await self._headers()
            
            # 1. Создаем черновик
            draft_resp = await client.post(draft_url, headers=headers, json=payload)
            draft_resp.raise_for_status()
            draft_data = draft_resp.json()
            
            draft_id = draft_data.get("id")
            conversation_id = draft_data.get("conversationId")

            # 2. Отправляем черновик
            send_url = f"{GRAPH_BASE}/users/{mailbox}/messages/{draft_id}/send"
            send_resp = await client.post(send_url, headers=headers)
            send_resp.raise_for_status()

            return {
                "id": draft_id,
                "conversationId": conversation_id,
            }
