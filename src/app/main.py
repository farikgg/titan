import uvicorn

from fastapi import FastAPI, Depends
from src.db.models.user_model import UserModel
from src.db.initialize import get_db
from src.schemas.user_schema import UserSchema
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.lifespan import lifespan
from src.api.v1.users.router import router as users_router


app = FastAPI(
    title="My FastAPI App",
    description="My FastAPI App",
    version="0.0.1",
    lifespan=lifespan,
)
app.include_router(users_router)

if __name__ == "__main__":
    uvicorn.run(app='src.app.main:app', reload=True)