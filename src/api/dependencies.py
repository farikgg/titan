from fastapi import Depends
from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.repositories.user_repo import UserRepository
from src.db.initialize import get_db


SessionDep = Annotated[AsyncSession, Depends(get_db)]

def get_user_repository(session: SessionDep):
    return UserRepository(session)

UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]

def get_user_service(repo: UserRepositoryDep):
    return UserService(repo)

UserServiceDep = Annotated[UserService, Depends(get_user_service)]