from enum import StrEnum


#           Константы для юзер фичей 

class TgUserRolesEnum(StrEnum):
    ADMIN = 'admin'
    HEAD_MANAGER = 'head_manager'
    MANAGER = 'manager'

ROLE_LIST = [role.value for role in TgUserRolesEnum]

#для составления Check условия в UserModel таблице, там необходим чистый sql.
def build_string_of_tg_roles():
    return ','.join(f"'{role}'" for role in ROLE_LIST)

#  все поля, которые можно заапдейтить после добавления в табицу users
USER_UPDATABLE_FIELDS = {'password', 'role'} 

#----------------------------------------------------------------------
