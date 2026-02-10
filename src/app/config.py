from pydantic_settings import BaseSettings, SettingsConfigDict



class BitrixStages(BaseSettings):
    DEAL_NEW: str = "C2:NEW"
    DEAL_WON: str = "C2:WON"
    DEAL_PAID: str = "C2:WON"  # если оплата = WON, иначе свой ID


class Settings(BaseSettings):
    DATABASE_URL: str
    BITRIX_WEBHOOK: str | None = None
    GROQ_API_KEY: str | None = None
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    IMAP_HOST: str = "outlook.office365.com"
    IMAP_PORT: int = 993
    EMAIL_USER: str
    EMAIL_APP_PASSWORD: str
    REDIS_HOST: str
    REDIS_PORT: int
    ADMIN_SECRET_TOKEN: str
    SKF_API_KEY: str
    SKF_API_SECRET: str
    SKF_SALES_UNIT_ID: str
    SKF_CUSTOMER_ID: str
    AZURE_TENANT_ID: str
    AZURE_CLIENT_ID: str
    AZURE_CLIENT_SECRET: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra='ignore'
    )

settings = Settings()
