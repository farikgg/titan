from pydantic import BaseModel
from src.core.constants import TgUserRolesEnum

class UserCreateSchema(BaseModel):
    username: str
    password: str
    role: TgUserRolesEnum

