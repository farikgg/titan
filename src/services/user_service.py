from src.db.models.user_model import UserModel
from src.schemas.user_schema import UserCreateSchema
from src.repositories.user_repo import UserRepository

class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def create_user(self, user_in: UserCreateSchema) -> UserModel:
        return await self.repo.add(user_in)

    async def get_user(self, user_id: int) -> UserModel:
        return await self.repo.get_by_id(user_id)

    async def update_user_password(self, user_id: int, new_password: str) -> UserModel:
        user = await self.repo.get_by_id(user_id)
        return await self.repo.update_password(user, new_password)

    async def delete_user(self, user_id: int) -> bool:
        return await self.repo.delete_by_id(user_id)

    async def verify_password(self, user_id: int, password: str) -> bool:
        user = await self.repo.get_by_id(user_id)
        return user.check_password(password)