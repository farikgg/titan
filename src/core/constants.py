from enum import StrEnum


#           Константы для юзер фичей 

class TgUserRolesEnum(StrEnum):
    ADMIN = 'parse'
    HEAD_MANAGER = 'head_manager'
    MANAGER = 'manager'

ROLE_LIST = [role.value for role in TgUserRolesEnum]


#  все поля, которые можно заапдейтить после добавления в табицу users
USER_UPDATABLE_FIELDS = {'password', 'role'} 

#----------------------------------------------------------------------
