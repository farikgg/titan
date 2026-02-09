from enum import Enum


class Role(str, Enum):
    manager = "manager"
    head_manager = "head-manager"
    admin = "admin"
