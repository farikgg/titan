
from src.db.models.user_model import UserModel
from src.schemas.user_schema import UserCreateSchema
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from src.core.exceptions import UserAlreadyExistsError, UserDoesNotExistError, UserCannotBeDeletedError

class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_in: UserCreateSchema):
        new_user = UserModel(username=user_in.username)
        new_user.password = user_in.password
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



    async def update_password(self, user: UserModel, new_password: str):

        if not user:
            raise UserDoesNotExistError()
        
        user.password = new_password

        await self.session.flush()
        await self.session.refresh(user)

        return user



    async def delete_by_id(self, user_id: int):
        user: UserModel = await self.session.get(UserModel, user_id)
        
        if not user:
            raise UserDoesNotExistError()
        try:
            await self.session.delete(user)
            await self.session.flush()
        except:
            await self.session.rollback()
            raise UserCannotBeDeletedError()

        return True



    async def check_password(self, user: UserModel, password: str):
        
        if not user:
            raise UserDoesNotExistError()
        
        is_correct_password = user.check_password(password)

        return is_correct_password