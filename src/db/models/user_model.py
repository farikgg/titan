import bcrypt

from src.db.initialize import Base
from src.core.enums import Role

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, CheckConstraint


class UserModel(Base):
    __tablename__ = "users"


    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    bitrix_user_id: Mapped[int] = mapped_column(nullable=False)

    role: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        server_default=Role.manager.value,
    )

    __table_args__ = (
        CheckConstraint(
            f"role in ('{Role.manager.value}', '{Role.head_manager.value}', '{Role.admin.value}')"
        ),
    )

    def set_password(self, password: str):
        salt = bcrypt.gensalt()
        password = password.encode('utf-8')
        hash_in_bytes = bcrypt.hashpw(password, salt)
        self.password_hash = hash_in_bytes.decode('utf-8')

    def check_password(self, password:str):
        correct_password = self.password_hash.encode('utf-8')
        entered_password = password.encode('utf-8')
        return bcrypt.checkpw(entered_password, correct_password)

    @property
    def password(self):
        raise AttributeError("Пароль read-only")

    @password.setter
    def password(self, password: str):
        self.set_password(password)
    
