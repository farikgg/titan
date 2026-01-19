from pydantic import BaseModel, ConfigDict
from src.core.constants import TgUserRolesEnum
from typing import Optional


class UserBase(BaseModel):
    username: str
    role: TgUserRolesEnum

class UserCreate(UserBase):
    password: str

class UserRead(UserBase):
    id: int

    model_config = ConfigDict(
        from_attributes=True 
    )

class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[TgUserRolesEnum] = None
    
class UserPasswordCheck(BaseModel):
    password: str

class UserPasswordUpdate(BaseModel):
    new_password: str

