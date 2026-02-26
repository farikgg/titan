from pydantic_settings import BaseSettings, SettingsConfigDict


class BitrixStages(BaseSettings):
    """
    Стадии воронки «Гидротех» в Bitrix24.
    CATEGORY_ID = 2  →  все стадии имеют префикс C2:

    Жизненный цикл сделки:
      NEW → PREPARATION → KP_CREATED → KP_SENT → WON / LOSE
    """
    CATEGORY_ID: int = 2

    NEW: str = "C2:NEW"                  # Новая заявка
    PREPARATION: str = "C2:PREPARATION"  # Подготовка КП (товары добавлены)
    KP_CREATED: str = "C2:KP_CREATED"    # КП сформировано (PDF готов)
    KP_SENT: str = "C2:KP_SENT"          # КП отправлено клиенту
    WON: str = "C2:WON"                  # Сделка выиграна
    LOSE: str = "C2:LOSE"                # Сделка проиграна

    # Допустимые переходы: из стадии → в какие стадии можно перейти
    @property
    def allowed_transitions(self) -> dict[str, list[str]]:
        return {
            self.NEW: [self.PREPARATION, self.LOSE],
            self.PREPARATION: [self.KP_CREATED, self.LOSE],
            self.KP_CREATED: [self.KP_SENT, self.PREPARATION, self.LOSE],
            self.KP_SENT: [self.WON, self.LOSE, self.PREPARATION],
            self.WON: [],
            self.LOSE: [self.NEW],
        }


BITRIX_STAGES = BitrixStages()


class Settings(BaseSettings):
    DATABASE_URL: str
    BITRIX_WEBHOOK: str | None = None
    GROQ_API_KEY: str | None = None
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
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra='ignore'
    )

settings = Settings()
