from pydantic import BaseModel, ConfigDict
from typing import Optional
from src.core.enums import Role


class UserBase(BaseModel):
    username: str
    role: Role

class UserCreate(UserBase):
    tg_id: int
    bitrix_user_id: int

class UserRead(UserBase):
    id: int
    tg_id: int
    bitrix_user_id: int

    model_config = ConfigDict(
        from_attributes=True 
    )

class UserUpdate(BaseModel):
    username: Optional[str] = None
    role: Optional[Role] = None
    tg_id: Optional[int] = None
    bitrix_user_id: Optional[int] = None