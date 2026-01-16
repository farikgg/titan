from fastapi import APIRouter

from fastapi import Depends, HTTPException
from src.db.models.user_model import UserModel
from src.db.initialize import get_db
from src.schemas.user_schema import UserSchema
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter( prefix='/users',
                     tags=["Users"] )

@router.post('/add')
async def add_user(userIn: UserSchema, session: AsyncSession = Depends(get_db)):
    new_user = UserModel(username=userIn.username, password=userIn.password)
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    await session.close()
    return { "id" : new_user.id,
             "username" : new_user.username, 
             "password_hash_slice" : new_user.password_hash[:7]}

@router.post('/get/{id}')
async def get_by_id(id: int, session: AsyncSession = Depends(get_db)):
    user: UserModel = await session.get(UserModel, id)

    if not user:
        return HTTPException(status_code=404, detail=f"User with id {id} not found")

    return {"id": user.id, "username" : user.username}


@router.post('/update_password/{id}')
async def update_password(id: int, new_password: str, session: AsyncSession = Depends(get_db)):
    user: UserModel = await session.get(UserModel, id)

    if not user:
        return HTTPException(status_code=404, detail=f"User with id {id} not found")
    
    user.password = new_password
    await session.commit()
    await session.refresh(user)
    return { "id" : {user.id},
             "username" : user.username }


@router.post('/delete/{id}')
async def delete_by_id(id: int, session: AsyncSession = Depends(get_db)):
    user: UserModel = await session.get(UserModel, id)
    
    if not user:
        return HTTPException(status_code=404, detail=f"User with id {id} not found")
    
    await session.delete(user)
    await session.commit()

    return { "id": id,
             "details" : f"User {id} deleted successfully"}

@router.post('/check_password/{id}')
async def check_password(id: int, password: str, session: AsyncSession = Depends(get_db)):
    user: UserModel = await session.get(UserModel, id)

    if not user:
        return HTTPException(status_code=404, detail=f"User with id {id} not found")
    
    is_correct_password = user.check_password(password)
    return {"username" : user.username, "is_correct_password" : is_correct_password}