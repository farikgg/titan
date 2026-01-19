from src.core.constants import ROLE_LIST

#для составления Check условия в UserModel таблице, там необходим чистый sql.
def build_string_of_tg_roles():
    return ','.join(f"'{role}'" for role in ROLE_LIST)