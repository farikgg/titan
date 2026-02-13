from src.db.models.user_model import UserModel
from src.schemas.user_schema import UserCreate, UserUpdate
from src.repositories.user_repo import UserRepository
from src.core.exceptions import (
                                UserDoesNotExistError,
                                UserCannotBeDeletedError,
                                UserUpdateError,
                                UserCreateError
                                )


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def add_user(self, user_schema: UserCreate) -> UserModel:
        user = UserModel(**user_schema.model_dump())
        try:
            await self.repo.add(user)
            await self.repo.session.commit()
        except Exception:
            await self.repo.session.rollback()
            raise UserCreateError()
        return user

    async def get_user(self, user_id: int) -> UserModel:
        user = await self.repo.get_by_id(user_id)

        if not user:
            raise UserDoesNotExistError()

        return user

    async def update_user_fields(self, user_id: int, data: dict) -> UserModel:
        user = await self.repo.get_by_id(user_id)

        if not user:
            raise UserDoesNotExistError()

        try:
            user = await self.repo.update(user, data)
            await self.repo.session.commit()
        except Exception:
            await self.repo.session.rollback()
            raise UserUpdateError()

        return user

    async def delete_user(self, user_id: int) -> bool:
        user = await self.repo.get_by_id(user_id)

        if not user:
            raise UserDoesNotExistError()

        try:
            await self.repo.delete(user)
            await self.repo.session.commit()
        except Exception:
            await self.repo.session.rollback()
            raise UserCannotBeDeletedError()

        return user_id
