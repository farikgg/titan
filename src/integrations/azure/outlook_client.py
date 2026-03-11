import base64
import httpx
from typing import List, Optional

from src.core.graph_auth import GraphAuth


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookClient:
    def __init__(self, auth: GraphAuth, mailbox: str | None = None, folder_name: str = "Inbox"):
        """
        Args:
            auth: GraphAuth instance
            mailbox: Email address (один аккаунт, например "testAI@tpgt-titan.com").
                    If None, uses default from settings or "testAI@tpgt-titan.com"
            folder_name: Название папки для чтения писем (например, "Inbox" или "Requests").
                        По умолчанию "Inbox"
        """
        self.auth = auth
        self.mailbox = mailbox
        self.folder_name = folder_name

    async def _headers(self):
        token = await self.auth.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_folder_id(self, folder_name: str) -> Optional[str]:
        """
        Находит ID папки по её названию (displayName).
        
        Args:
            folder_name: Название папки (например, "Inbox", "Requests")
        
        Returns:
            ID папки или None если не найдена
        """
        mailbox = self.mailbox or "testAI@tpgt-titan.com"
        url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders"
        
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=await self._headers())
            resp.raise_for_status()
            folders = resp.json().get("value", [])
            
            # Ищем папку по displayName
            for folder in folders:
                if folder.get("displayName") == folder_name:
                    return folder.get("id")
            
            return None

    async def create_folder(self, folder_name: str, parent_folder_id: str = "Inbox") -> Optional[str]:
        """
        Создаёт новую папку в почтовом ящике.
        
        Args:
            folder_name: Название новой папки
            parent_folder_id: ID родительской папки (по умолчанию "Inbox")
        
        Returns:
            ID созданной папки или None если ошибка
        """
        mailbox = self.mailbox or "testAI@tpgt-titan.com"
        url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders/{parent_folder_id}/childFolders"
        
        payload = {
            "displayName": folder_name,
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(url, headers=await self._headers(), json=payload)
                resp.raise_for_status()
                folder_data = resp.json()
                return folder_data.get("id")
            except httpx.HTTPStatusError as e:
                # Если папка уже существует (409 Conflict), пытаемся найти её
                if e.response.status_code == 409:
                    return await self.get_folder_id(folder_name)
                return None

    async def get_or_create_folder(self, folder_name: str) -> str:
        """
        Получает ID папки, если она существует, или создаёт новую.
        
        Args:
            folder_name: Название папки
        
        Returns:
            ID папки
        """
        # Сначала пытаемся найти существующую папку
        folder_id = await self.get_folder_id(folder_name)
        if folder_id:
            return folder_id
        
        # Если не найдена - создаём
        folder_id = await self.create_folder(folder_name)
        if folder_id:
            return folder_id
        
        # Если не удалось создать - используем Inbox как fallback
        return "Inbox"

    async def fetch_last_messages(self, limit: int = 5) -> List[dict]:
        """
        Получает последние письма из указанной папки.
        Если папка не указана, использует "Inbox".
        Если папка не существует, пытается создать её.
        """
        mailbox = self.mailbox or "testAI@tpgt-titan.com"
        folder_name = self.folder_name or "Inbox"
        
        # Получаем или создаём папку
        folder_id = await self.get_or_create_folder(folder_name)
        
        url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders/{folder_id}/messages"
        params = {
            "$top": limit,
            "$orderby": "receivedDateTime DESC",
            "$expand": "attachments",
        }

        async with httpx.AsyncClient(timeout=30) as client:
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
