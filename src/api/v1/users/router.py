from fastapi import APIRouter


from src.api.dependencies import UserServiceDep
from src.schemas.user_schema import UserCreateSchema

router = APIRouter( prefix='/users',
                     tags=["Users"] )



@router.post('/add')
async def add_user(user_schema: UserCreateSchema, user_service: UserServiceDep):
    user = await user_service.add_user(user_schema)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role
    }

@router.get('/{id}')
async def get_by_id(id: int, user_service: UserServiceDep):
    user = await user_service.get_user(id)
    return {"id": user.id,
            "username": user.username,
            "role": user.role}

@router.post('/update_password/{id}')
async def update_password(id: int, new_password: str, user_service: UserServiceDep):
    user = await user_service.update_user_password(id, new_password)
    return {"id": user.id, "details": f"Password for user {id} updated"}

@router.delete('/delete/{id}')
async def delete_by_id(id: int, user_service: UserServiceDep):
    await user_service.delete_user(id)
    return {"id": id, "details": f"User {id} deleted successfully"}

@router.post('/check_password/{id}')
async def check_password(id: int, password: str, user_service: UserServiceDep):
    is_correct = await user_service.verify_password(id, password)
    return {"id": id, "password_correct": is_correct}
