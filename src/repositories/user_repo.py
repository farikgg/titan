
from src.db.models.user_model import UserModel
from src.schemas.user_schema import UserCreateSchema
from src.core.exceptions import UserAlreadyExistsError, UserDoesNotExistError, UserCannotBeDeletedError
from src.core.constants import USER_UPDATABLE_FIELDS

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_schema: UserCreateSchema):
        new_user = UserModel(**user_schema.model_dump())
        new_user.password = user_schema.password
        try:
            self.session.add(new_user)
            await self.session.flush()
            await self.session.refresh(new_user)
        except IntegrityError:
            await self.session.rollback()
            raise UserAlreadyExistsError(new_user.username)
            
        return new_user



    async def get_by_id(self, user_id: int):
        user: UserModel = await self.session.get(UserModel, user_id)

        if not user:
            raise UserDoesNotExistError()

        return user



    async def update(self, user: UserModel, data: dict):
        
        if not user:
            raise UserDoesNotExistError()
        
        #Костыль, потому что нижняя функция не сработает с аттрибутом созданным через @property
        password = data.pop('password', None)
        if password:
            user.password = password

        for k, v in data.items():
            if k in USER_UPDATABLE_FIELDS:
                if hasattr(user, k):
                    setattr(user, k, v)


        await self.session.flush()

        return user



    async def delete_by_id(self, user_id: int):
        user: UserModel = await self.session.get(UserModel, user_id)
        
        if not user:
            raise UserDoesNotExistError()
        try:
            await self.session.delete(user)
            await self.session.flush()
        except Exception:
            await self.session.rollback()
            raise UserCannotBeDeletedError()

        return True




    async def check_password(self, user: UserModel, password: str):
        if not user:
            raise UserDoesNotExistError()
    
        return user.check_password(password)