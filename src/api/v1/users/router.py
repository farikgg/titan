from fastapi import APIRouter, status


from src.api.dependencies import UserServiceDep
from src.schemas.user_schema import UserCreate, UserRead,UserUpdate

router = APIRouter( prefix='/users',
                     tags=["Users"] )



@router.post('/add', response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def add_user(user_schema: UserCreate, user_service: UserServiceDep):
    user = await user_service.add_user(user_schema)
    return UserRead.model_validate(user)

@router.get('/{id}', response_model=UserRead,status_code=status.HTTP_200_OK)
async def get_by_id(id: int, user_service: UserServiceDep):
    user = await user_service.get_user(id)
    return UserRead.model_validate(user)

@router.patch('/update/{id}', status_code=status.HTTP_200_OK)
async def update(id: int, data: UserUpdate, user_service: UserServiceDep):
    user = await user_service.update_user_fields(id, data.model_dump())
    return {"id": user.id, "details": "User updated successfully"}

@router.delete('/delete/{id}', status_code=status.HTTP_200_OK)
async def delete(id: int, user_service: UserServiceDep):
    await user_service.delete_user(id)
    return {"id": id, "details": f"User {id} deleted successfully"}
