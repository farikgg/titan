from pydantic_settings import BaseSettings, SettingsConfigDict


class BitrixStages(BaseSettings):
    """
    Стадии воронки «Гидротех» в Bitrix24.
    CATEGORY_ID = 9  →  все стадии имеют префикс C9:

    Жизненный цикл сделки:
      NEW → FINAL_INVOICE → EXECUTING → WON / LOSE / APOLOGY / LOSE_REASON
    """
    CATEGORY_ID: int = 9

    # Основные стадии воронки "Гидротех.Сделки"
    NEW: str = "C9:NEW"                     # Интерес или ТКП
    FINAL_INVOICE: str = "C9:FINAL_INVOICE" # Договор заключен. В работе
    EXECUTING: str = "C9:EXECUTING"         # АВР и Накладная подписаны
    WON: str = "C9:WON"                     # Сделка успешна
    LOSE: str = "C9:LOSE"                   # Нет финансирования
    APOLOGY: str = "C9:APOLOGY"             # Анализ причины провала
    LOSE_REASON_COMPETITOR: str = "C9:UC_BVSRBV"  # Конкуренты

    # Допустимые переходы: из стадии → в какие стадии можно перейти
    @property
    def allowed_transitions(self) -> dict[str, list[str]]:
        return {
            self.NEW: [
                self.FINAL_INVOICE,
                self.LOSE,
                self.APOLOGY,
                self.LOSE_REASON_COMPETITOR,
            ],
            self.FINAL_INVOICE: [
                self.EXECUTING,
                self.WON,
                self.LOSE,
                self.APOLOGY,
                self.LOSE_REASON_COMPETITOR,
            ],
            self.EXECUTING: [
                self.WON,
                self.LOSE,
                self.APOLOGY,
                self.LOSE_REASON_COMPETITOR,
            ],
            self.WON: [],
            self.LOSE: [],
            self.APOLOGY: [],
            self.LOSE_REASON_COMPETITOR: [],
        }


BITRIX_STAGES = BitrixStages()


class Settings(BaseSettings):
    DATABASE_URL: str
    BITRIX_WEBHOOK: str | None = None
    GROQ_API_KEY: str | None = None
    # Если REDIS_URL задан (например, redis://default:pass@host:6379/0),
    # он используется для Celery и LockService.
    # Иначе используется пара REDIS_HOST / REDIS_PORT.
    REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    ADMIN_SECRET_TOKEN: str
    SKF_API_KEY: str
    SKF_API_SECRET: str
    SKF_SALES_UNIT_ID: str
    SKF_CUSTOMER_ID: str
    AZURE_TENANT_ID: str
    AZURE_CLIENT_ID: str
    AZURE_CLIENT_SECRET: str
    EMAIL_USER: str | None = None  # Единый mailbox (например, "testAI@tpgt-titan.com")
    FUCHS_FOLDER: str = "Inbox"  # Папка для писем FUCHS (по умолчанию "Inbox")
    REQUESTS_FOLDER: str = "Requests"  # Папка для писем requests@... (будет создана автоматически)
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_TMA_BOT_TOKEN: str | None = None  # Альтернативный токен для Telegram Mini App
    TELEGRAM_CHAT_ID: str
    TELEGRAM_SKIP_SIGNATURE_CHECK: bool = False  # ВРЕМЕННО: отключить проверку подписи (только для теста!)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra='ignore'
    )

settings = Settings()
