
from src.db.models.user_model import UserModel

from sqlalchemy.ext.asyncio import AsyncSession



class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user: UserModel):
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)

            
        return user



    async def get_by_id(self, user_id: int):
        user: UserModel = await self.session.get(UserModel, user_id)

        return user



    async def update(self, user: UserModel, data: dict):
        
        #Костыль, потому что нижняя функция не сработает с аттрибутом созданным через @property
        password = data.pop('password', None)
        if password:
            user.password = password

        for k, v in data.items():
            if hasattr(user, k):
                setattr(user, k, v)


        await self.session.flush()

        return user



    async def delete(self, user: UserModel):
        await self.session.delete(user)
        await self.session.flush()
        return True




    async def check_password(self, user: UserModel, password: str):
        return user.check_password(password)