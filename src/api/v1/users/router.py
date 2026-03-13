from fastapi import APIRouter, status, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import UserServiceDep
from src.schemas.user_schema import UserCreate, UserRead,UserUpdate
from src.core.auth import get_tg_user, get_tg_user_or_admin
from src.db.models.user_model import UserModel
from src.db.initialize import get_db
from src.schemas.price_schema import PriceRead
from src.services.price_service import PriceService
from src.core.auth import require_admin

router = APIRouter( prefix='/users',
                     tags=["Users"] )
price_service = PriceService()


@router.post("/admin-only")
async def admin_endpoint(user: UserModel = Depends(require_admin)):
    return {"message": "OK"}


@router.post('/add', response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def add_user(user_schema: UserCreate, user_service: UserServiceDep):
    user = await user_service.add_user(user_schema)
    return UserRead.model_validate(user)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Получить текущего пользователя (TMA)",
    description="""
Возвращает текущего пользователя Telegram Mini App.

Авторизация происходит через заголовок:
X-Telegram-Init-Data

Если подпись Telegram некорректна → 401  
Если пользователь не зарегистрирован → 403
""",
)
async def get_me(current_user: UserModel = Depends(get_tg_user)):
    return UserRead.model_validate(current_user)


@router.get("/", response_model=list[UserRead])
async def list_users(
    user_service: UserServiceDep,
    _: UserModel = Depends(get_tg_user_or_admin),
):
    """
    Вернуть список пользователей для выпадающих списков и т.п.

    Авторизация:
      - через X-Telegram-Init-Data (TMA), или
      - через admin token в заголовке `token`.
    """
    users = await user_service.list_users()
    if users is None:
        raise HTTPException(status_code=404, detail="No users found")
    return [UserRead.model_validate(u) for u in users]


@router.get('/{id}', response_model=UserRead,status_code=status.HTTP_200_OK)
async def get_by_id(id: int, user_service: UserServiceDep):
    user = await user_service.get_user(id)
    return UserRead.model_validate(user)


@router.patch('/update/{id}', status_code=status.HTTP_200_OK)
async def update(id: int, data: UserUpdate, user_service: UserServiceDep):
    user = await user_service.update_user_fields(id, data.model_dump())
    return {"id": user.id, "details": "User updated successfully"}


@router.delete('/delete/{id}', status_code=status.HTTP_200_OK)
async def delete(id: int, user_service: UserServiceDep):
    await user_service.delete_user(id)
    return {"id": id, "details": f"User {id} deleted successfully"}


@router.get("/search/{art}", response_model=PriceRead)
async def search_single(
    art: str,
    db: AsyncSession = Depends(get_db),
    _auth = Depends(get_tg_user) # Защита роутера
):
    return await price_service.get_price(db, art)
