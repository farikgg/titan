from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    BITRIX_WEBHOOK: str | None = None
    GROQ_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra='ignore'
    )

class EmailConfig(BaseSettings):
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    IMAP_HOST: str = "outlook.office365.com"
    IMAP_PORT: int = 993
    EMAIL_USER: str
    EMAIL_PASSWORD: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra='ignore'
    )


settings = Settings()
