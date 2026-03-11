from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.initialize import async_session
from src.db.models.user_model import UserModel



class UserRepository:
    def __init__(self, session: AsyncSession):
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

    async def get_by_tg_id(self, tg_id: int):
        result = await self.session.execute(
            select(UserModel).where(UserModel.tg_id == tg_id)
        )
        return result.scalar_one_or_none()

    async def get_by_bitrix_user_id(self, bitrix_user_id: int):
        """Находит пользователя по Bitrix user ID"""
        result = await self.session.execute(
            select(UserModel).where(UserModel.bitrix_user_id == bitrix_user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(tg_id: int, username: str):
        async with async_session() as session:
            user = UserModel(
                tg_id=tg_id,
                username=username or "unknown"
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    @staticmethod
    async def get_or_create(tg_id: int, username: str):
        async with async_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_tg_id(tg_id)
        if user:
            return user
        return await UserRepository.create(tg_id, username)
