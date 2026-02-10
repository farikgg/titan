import base64
import httpx
from typing import List

from src.core.graph_auth import GraphAuth


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookClient:
    def __init__(self, auth: GraphAuth):
        self.auth = auth

    async def _headers(self):
        token = await self.auth.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def fetch_last_messages(self, limit: int = 5) -> List[dict]:
        url = (
            f"{GRAPH_BASE}/users/testAI@tpgt-titan.com/mailFolders/Inbox/messages"
            "?$top={limit}"
            "&$orderby=receivedDateTime DESC"
            "&$expand=attachments"
        )
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
