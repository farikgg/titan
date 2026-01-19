from src.db.models.user_model import UserModel
from src.schemas.user_schema import UserCreateSchema
from src.repositories.user_repo import UserRepository

class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def add_user(self, user_schema: UserCreateSchema) -> UserModel:
        user = await self.repo.add(user_schema)
        await self.repo.session.commit()
        return user

    async def get_user(self, user_id: int) -> UserModel:
        user = await self.repo.get_by_id(user_id)
        return user

    async def update_user_password(self, user_id: int, new_password: str) -> UserModel:
        user = await self.repo.get_by_id(user_id)
        result = await self.repo.update(user, data={'password' : new_password})
        await self.repo.session.commit()
        return result
    
    async def update_user_fields(self, user_id: int, data: dict) -> UserModel:
        '''принимает data: dict по типу {'password' : 'abc', 'role' : 'head_manager'}'''
        user = await self.repo.get_by_id(user_id)
        result = await self.repo.update(user, data)
        await self.repo.session.commit()
        return result
    
    async def delete_user(self, user_id: int) -> bool:
        await self.repo.delete_by_id(user_id)
        await self.repo.session.commit()
        return user_id

    async def verify_password(self, user_id: int, password: str) -> bool:
        user = await self.repo.get_by_id(user_id)
        return user.check_password(password)