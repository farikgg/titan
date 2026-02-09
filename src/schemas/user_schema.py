from pydantic import BaseModel, ConfigDict
from typing import Optional
from src.core.enums import Role


class UserBase(BaseModel):
    username: str
    role: Role

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
    role: Optional[Role] = None
    
class UserPasswordCheck(BaseModel):
    password: str

class UserPasswordUpdate(BaseModel):
    new_password: str

