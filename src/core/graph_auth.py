import httpx
import time
from src.app.config import settings


class GraphAuth:
    """
    Получает access token для Microsoft Graph
    Без кеша (пока)
    """

    def __init__(self):
        self.tenant_id = settings.AZURE_TENANT_ID
        self.client_id = settings.AZURE_CLIENT_ID
        self.client_secret = settings.AZURE_CLIENT_SECRET

        self._token = None
        self._expires_at = 0

    async def get_token(self) -> str:
        # простейшая защита от лишних запросов
        if self._token and time.time() < self._expires_at:
            return self._token

        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            payload = resp.json()

        self._token = payload["access_token"]
        self._expires_at = time.time() + payload.get("expires_in", 3599) - 60

        return self._token
