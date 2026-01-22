
class UserError(Exception):
    ...
class UserAlreadyExistsError(UserError):
    def __init__(self, username: str):
        self.username = username
        self.message = f"User '{username}' already exists."
        super().__init__(self.message)

class UserDoesNotExistError(UserError):
    def __init__(self):
        self.message = f"User does not exist."
        super().__init__(self.message)

class UserCannotBeDeletedError(UserError):
    def __init__(self):
        self.message = f"Cannot delete user from the database."
        super().__init__(self.message)

class UserUpdateError(UserError):
    def __init__(self):
        self.message = f"Cannot update user in the database."
        super().__init__(self.message)

class UserCreateError(UserError):
    def __init__(self):
        self.message = f"Cannot create user in the database."
        super().__init__(self.message)

class UserIsNotValidError(UserError):
    def __init__(self):
        self.message = f"Wrong Admin Token! Can't parse email."