from fast_bitrix24 import Bitrix
from src.app.config import settings
"""
интеграция битрикса
"""

def get_bitrix_client() -> Bitrix:
    return Bitrix(webhook=settings.BITRIX_WEBHOOK)
