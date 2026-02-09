import pytest
from src.services.deal_service import DealService
from src.core.enums import Role

class DummyUser:
    def __init__(self, role, bitrix_user_id):
        self.role = role
        self.bitrix_user_id = bitrix_user_id

@pytest.mark.asyncio
async def test_manager_sees_only_own_deals(mocker):
    bitrix = mocker.Mock()
    bitrix.get_deals = mocker.AsyncMock(return_value=["own"])
    bitrix.get_all_deals = mocker.AsyncMock(return_value=["all"])

    service = DealService(bitrix, None)

    user = DummyUser(Role.manager.value, 123)
    deals = await service.list_deals_for_user(user)

    assert deals == ["own"]
