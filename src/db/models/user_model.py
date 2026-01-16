from src.db.initialize import Base

import bcrypt,asyncio
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String


class UserModel(Base):
    __tablename__ = "users"

    id:Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128),nullable=False)



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
