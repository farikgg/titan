import pytest
import respx
from httpx import Response
from unittest.mock import MagicMock, AsyncMock, patch
from src.integrations.azure.outlook_client import OutlookClient

@pytest.mark.asyncio
@respx.mock
async def test_outlook_client_mark_as_read():
    mock_auth = MagicMock()
    mock_auth.get_token = AsyncMock(return_value="fake_token")
    client = OutlookClient(auth=mock_auth)
    message_id = "MSG123"
    
    # Mock the PATCH request to Azure Graph API
    # OutlookClient uses /users/{mailbox}/messages/{id} logic
    url = f"https://graph.microsoft.com/v1.0/users/testAI@tpgt-titan.com/messages/{message_id}"
    route = respx.patch(url).mock(return_value=Response(200, json={}))
    
    # Mock token getting is already handled by mock_auth.get_token
    await client.mark_as_read(message_id)
    
    # Verify the request was made correctly
    assert route.called
    request = route.calls.last.request
    import json
    payload = json.loads(request.content)
    assert payload == {"isRead": True}

from unittest.mock import patch
