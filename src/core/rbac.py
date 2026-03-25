from fastapi import Depends, HTTPException, status
from src.core.enums import Role

ROLE_LEVELS = {
    Role.manager: 1,
    Role.head_manager: 2,
    Role.admin: 3,
}

POLICIES = {
    # prices
    "prices.read": Role.manager,
    "prices.write": Role.head_manager,

    # deals
    "deals.read": Role.manager,
    "deals.write": Role.manager,
    "deals.override": Role.head_manager,

    # admin
    "users.read": Role.head_manager,
    "users.write": Role.admin,
}


def require_min_role(min_role: Role):
    from src.core.auth import get_tg_user_or_admin
    min_level = ROLE_LEVELS[min_role]

    def checker(user=Depends(get_tg_user_or_admin)):
        user_role = Role(user.role)
        if ROLE_LEVELS[user_role] < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return checker


def require_permission(permission: str):
    min_role = POLICIES.get(permission)
    if not min_role:
        raise RuntimeError(f"Unknown permission: {permission}")

    return require_min_role(min_role)
