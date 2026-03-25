import logging
from typing import List, Dict, Optional

from anyio import to_thread
from pathlib import Path
from fast_bitrix24 import Bitrix
from fast_bitrix24.server_response import ErrorInServerResponseException
import httpx

from src.app.config import BITRIX_STAGES, settings

logger = logging.getLogger(__name__)


class BitrixService:
    def __init__(self, bx: Bitrix):
        self.bx = bx

    @staticmethod
    def _im_not_supported_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "error_method_not_found" in msg
            or "method not found" in msg
            or "unknown method" in msg
            or "method unavailable" in msg
        )

    async def get_deals(self, bitrix_user_id: int, stage_id: str | None = None) -> List[Dict]:
        try:
            # Сначала пробуем найти сделки в воронке Гидротех (CATEGORY_ID = 9)
            # Используем get_all() для методов .list, как рекомендует fast_bitrix24
            filter_dict = {
                "ASSIGNED_BY_ID": bitrix_user_id,
                "CATEGORY_ID": BITRIX_STAGES.CATEGORY_ID,
                "CLOSED": "N",
            }
            # Если указана стадия — добавляем фильтр
            if stage_id:
                filter_dict["STAGE_ID"] = stage_id
            
            result = await to_thread.run_sync(
                self.bx.get_all,
                "crm.deal.list",
                {
                    "filter": filter_dict,
                    "select": [
                        "ID",
                        "TITLE",
                        "STAGE_ID",
                        "CATEGORY_ID",
                        "OPPORTUNITY",
                        "CURRENCY_ID",
                        "ASSIGNED_BY_ID",
                    ],
                },
            )
            # get_all() всегда возвращает список
            deals = list(result) if result else []
            logger.info(
                "Bitrix: найдено %d сделок для пользователя %s в воронке %s",
                len(deals),
                bitrix_user_id,
                BITRIX_STAGES.CATEGORY_ID,
            )
            
            # Если в воронке Гидротех ничего нет — пробуем все незакрытые сделки пользователя
            if not deals:
                logger.info(
                    "Bitrix: сделок в воронке %s не найдено, ищу все незакрытые сделки пользователя %s",
                    BITRIX_STAGES.CATEGORY_ID,
                    bitrix_user_id,
                )
                result = await to_thread.run_sync(
                    self.bx.get_all,
                "crm.deal.list",
                {
                    "filter": {
                        "ASSIGNED_BY_ID": bitrix_user_id,
                        "CLOSED": "N",
                    },
                    "select": [
                        "ID",
                        "TITLE",
                        "STAGE_ID",
                        "CATEGORY_ID",
                        "OPPORTUNITY",
                        "CURRENCY_ID",
                        "ASSIGNED_BY_ID",
                    ],
                },
            )
                # get_all() всегда возвращает список
                deals = list(result) if result else []
                logger.info(
                    "Bitrix: найдено %d незакрытых сделок пользователя %s (все воронки)",
                    len(deals),
                    bitrix_user_id,
                )
            
            return deals
        except Exception:
            logger.exception("Bitrix: ошибка получения списка сделок")
            return []

    async def get_deal(self, deal_id: int) -> Optional[Dict]:
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.get",
                {"id": deal_id},
            )
            
            # fast_bitrix24 может вернуть словарь с ключом "result" или список/обёртку
            if isinstance(result, dict):
                # Если есть ключ "result" — извлекаем данные оттуда
                if "result" in result:
                    inner_result = result["result"]
                    # Если внутри словарь — это и есть сделка
                    if isinstance(inner_result, dict):
                        result = inner_result
                    # Если внутри список — берём первый элемент
                    elif isinstance(inner_result, list):
                        result = inner_result[0] if inner_result else None
                    else:
                        result = inner_result
                # Если нет ключа "result", но есть "ID" — это уже сделка
                elif "ID" in result:
                    pass  # result уже правильный
                else:
                    # Некоторые интеграции Bitrix возвращают обёртку вида:
                    # {"order0000000000": { "ID": "...", ... }}
                    # Если видим один ключ и внутри словарь с ID — разворачиваем.
                    if len(result) == 1:
                        only_value = next(iter(result.values()))
                        if isinstance(only_value, dict) and "ID" in only_value:
                            result = only_value
                        else:
                            logger.warning(
                                "Bitrix: get_deal вернул словарь без 'ID' и без 'result' "
                                "(один ключ, но неожиданное значение). Тип: %s, ключи: %s, значение: %s",
                                type(result),
                                list(result.keys()),
                                result,
                            )
                    else:
                        logger.warning(
                            "Bitrix: get_deal вернул словарь без 'ID' и без 'result'. "
                            "Тип: %s, ключи: %s, значение: %s",
                            type(result),
                            list(result.keys()),
                            result,
                        )
            elif isinstance(result, list):
                # Если список — берём первый элемент
                result = result[0] if result else None
            elif result is None:
                logger.warning("Bitrix: get_deal(%s) вернул None", deal_id)
                return None
            else:
                logger.warning(
                    "Bitrix: get_deal(%s) вернул неожиданный тип: %s, значение: %s",
                    deal_id,
                    type(result),
                    result,
                )
                return None

            # Проверяем, что результат — это словарь с ключом "ID"
            if not isinstance(result, dict):
                logger.error(
                    "Bitrix: get_deal(%s) вернул не словарь после обработки. Тип: %s, значение: %s",
                    deal_id,
                    type(result),
                    result,
                )
                return None
            
            if "ID" not in result:
                logger.error(
                    "Bitrix: get_deal(%s) вернул словарь без ключа 'ID'. Ключи: %s, значение: %s",
                    deal_id,
                    list(result.keys()),
                    result,
                )
                return None

            logger.debug("Bitrix: get_deal(%s) → ID=%s", deal_id, result.get("ID"))
            return result
        except ErrorInServerResponseException as e:
            # Проверяем, это "Access denied" или "Not found"
            error_info = str(e)
            if "Access denied" in error_info or "access denied" in error_info.lower():
                logger.error(
                    "Bitrix: ACCESS DENIED при получении сделки %s. "
                    "Проверьте права пользователя/токена Bitrix на эту сделку. Ошибка: %s",
                    deal_id,
                    error_info,
                )
            elif "Not found" in error_info or "not found" in error_info.lower():
                logger.warning("Bitrix: сделка %s не найдена", deal_id)
            else:
                logger.error(
                    "Bitrix: ошибка получения сделки %s (ErrorInServerResponseException): %s",
                    deal_id,
                    error_info,
                )
            return None
        except Exception:
            logger.exception("Bitrix: ошибка получения сделки %s", deal_id)
            return None

    async def get_deal_products(self, deal_id: int) -> List[Dict]:
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.productrows.get",
                {"id": deal_id},
            )
            # fast_bitrix24 может вернуть словарь с ключом "result" или список напрямую
            if isinstance(result, dict):
                # Если это словарь, возможно товары в result["result"] или result
                products = result.get("result", result)
                if isinstance(products, list):
                    return products
                elif isinstance(products, dict):
                    # Если это один товар в виде словаря, оборачиваем в список
                    return [products] if products else []
                else:
                    logger.warning(
                        "Bitrix: get_deal_products вернул неожиданный тип: %s, значение: %s",
                        type(products),
                        products,
                    )
                    return []
            elif isinstance(result, list):
                # Если это уже список — возвращаем как есть
                return result
            else:
                logger.warning(
                    "Bitrix: get_deal_products вернул неожиданный тип: %s, значение: %s",
                    type(result),
                    result,
                )
                return []
        except Exception:
            logger.exception(
                "Bitrix: ошибка получения товаров сделки %s", deal_id
            )
            return []

    async def get_all_deals(self, stage_id: str | None = None) -> List[Dict]:
        try:
            # Сначала пробуем найти все сделки в воронке Гидротех (CATEGORY_ID = 9)
            # Используем get_all() для методов .list, как рекомендует fast_bitrix24
            filter_dict = {
                "CATEGORY_ID": BITRIX_STAGES.CATEGORY_ID,
                "CLOSED": "N",
            }
            # Если указана стадия — добавляем фильтр
            if stage_id:
                filter_dict["STAGE_ID"] = stage_id
            
            result = await to_thread.run_sync(
                self.bx.get_all,
                "crm.deal.list",
                {
                    "filter": filter_dict,
                    "select": [
                        "ID",
                        "TITLE",
                        "STAGE_ID",
                        "CATEGORY_ID",
                        "OPPORTUNITY",
                        "CURRENCY_ID",
                        "ASSIGNED_BY_ID",
                    ],
                },
            )
            # get_all() всегда возвращает список
            deals = list(result) if result else []
            logger.info(
                "Bitrix: найдено %d незакрытых сделок в воронке %s",
                len(deals),
                BITRIX_STAGES.CATEGORY_ID,
            )
            
            # Если в воронке Гидротех ничего нет — пробуем все незакрытые сделки
            if not deals:
                logger.info(
                    "Bitrix: сделок в воронке %s не найдено, ищу все незакрытые сделки",
                    BITRIX_STAGES.CATEGORY_ID,
                )
                result = await to_thread.run_sync(
                    self.bx.get_all,
                    "crm.deal.list",
                    {
                        "filter": {
                            "CLOSED": "N",
                        },
                        "select": [
                            "ID",
                            "TITLE",
                            "STAGE_ID",
                            "CATEGORY_ID",
                            "OPPORTUNITY",
                            "CURRENCY_ID",
                            "ASSIGNED_BY_ID",
                        ],
                    },
                )
                # get_all() всегда возвращает список
                deals = list(result) if result else []
                logger.info(
                    "Bitrix: найдено %d незакрытых сделок (все воронки)",
                    len(deals),
                )
            
            return deals
        except Exception:
            logger.exception("Bitrix: error fetching all deals")
            return []

    async def create_deal(self, fields: Dict) -> Optional[int]:
        """
        Создаёт сделку в воронке Гидротех.
        fields — словарь полей Bitrix24 (TITLE, OPPORTUNITY, …).
        CATEGORY_ID и STAGE_ID подставляются автоматически, если не указаны.
        """
        fields.setdefault("CATEGORY_ID", BITRIX_STAGES.CATEGORY_ID)
        fields.setdefault("STAGE_ID", BITRIX_STAGES.NEW)
        fields.setdefault("CURRENCY_ID", "KZT")

        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.add",
                {"fields": fields},
            )
            deal_id = int(result)
            logger.info(
                "Bitrix: сделка создана id=%s stage=%s",
                deal_id,
                fields["STAGE_ID"],
            )
            return deal_id
        except Exception:
            logger.exception("Bitrix: ошибка создания сделки")
            return None


    async def update_deal(self, deal_id: int, fields: Dict) -> bool:
        """Обновляет произвольные поля сделки."""
        try:
            await to_thread.run_sync(
                self.bx.call,
                "crm.deal.update",
                {"id": deal_id, "fields": fields},
            )
            logger.info("Bitrix: сделка %s обновлена, fields=%s", deal_id, list(fields.keys()))
            return True
        except ErrorInServerResponseException as e:
            # Проверяем, это "Access denied" или "Not found"
            error_info = str(e)
            if "Access denied" in error_info or "access denied" in error_info.lower():
                logger.error(
                    "Bitrix: ACCESS DENIED при обновлении сделки %s. "
                    "Проверьте права пользователя/токена Bitrix на эту сделку. "
                    "Поля: %s. Ошибка: %s",
                    deal_id,
                    list(fields.keys()),
                    error_info,
                )
            elif "Not found" in error_info or "not found" in error_info.lower():
                logger.warning("Bitrix: сделка %s не найдена для обновления", deal_id)
            else:
                logger.error(
                    "Bitrix: ошибка обновления сделки %s (ErrorInServerResponseException): %s",
                    deal_id,
                    error_info,
                )
            return False
        except Exception:
            logger.exception("Bitrix: ошибка обновления сделки %s", deal_id)
            return False

    async def update_deal_stage(self, deal_id: int, stage_id: str) -> bool:
        """
        Меняет стадию сделки с проверкой допустимого перехода.
        Если текущая стадия неизвестна (None или не в нашей карте) —
        обновляем принудительно с предупреждением.
        """
        deal = await self.get_deal(deal_id)
        if not deal:
            logger.error(
                "Bitrix: сделка %s недоступна для смены стадии "
                "(не найдена или нет доступа - проверьте логи выше)",
                deal_id,
            )
            return False

        current_stage = deal.get("STAGE_ID")

        # Если текущая стадия известна — проверяем допустимость
        if current_stage and current_stage in BITRIX_STAGES.allowed_transitions:
            allowed = BITRIX_STAGES.allowed_transitions[current_stage]
            if stage_id not in allowed:
                logger.warning(
                    "Bitrix: запрещённый переход %s → %s для сделки %s. Допустимые: %s",
                    current_stage,
                    stage_id,
                    deal_id,
                    allowed,
                )
                return False
        else:
            # Стадия неизвестна или не в нашей карте — обновляем принудительно
            logger.warning(
                "Bitrix: текущая стадия '%s' сделки %s не распознана. "
                "Принудительно устанавливаю %s",
                current_stage,
                deal_id,
                stage_id,
            )

        return await self.update_deal(deal_id, {"STAGE_ID": stage_id})


    async def set_deal_products(
        self, deal_id: int, products: List[Dict]
    ) -> bool:
        try:
            await to_thread.run_sync(
                self.bx.call,
                "crm.deal.productrows.set",
                {
                    "id": deal_id,
                    "rows": products,
                },
            )
            logger.info("Bitrix: товары сделки %s установлены (%d шт.)", deal_id, len(products))
            return True
        except ErrorInServerResponseException as e:
            # Проверяем, это "Access denied" или "Not found"
            error_info = str(e)
            if "Access denied" in error_info or "access denied" in error_info.lower():
                logger.error(
                    "Bitrix: ACCESS DENIED при установке товаров для сделки %s. "
                    "Проверьте права пользователя/токена Bitrix на эту сделку. "
                    "Товаров: %d. Ошибка: %s",
                    deal_id,
                    len(products),
                    error_info,
                )
            elif "Not found" in error_info or "not found" in error_info.lower():
                logger.warning("Bitrix: сделка %s не найдена для установки товаров", deal_id)
            else:
                logger.error(
                    "Bitrix: ошибка установки товаров для сделки %s (ErrorInServerResponseException): %s",
                    deal_id,
                    error_info,
                )
            return False
        except Exception:
            logger.exception(
                "Bitrix: ошибка установки товаров для сделки %s", deal_id
            )
            return False

    # ──────────────────────────────────────────────
    #  Файлы / КП в сделке
    # ──────────────────────────────────────────────

    async def attach_kp_pdf(self, deal_id: int, pdf_path: Path) -> bool:
        """
        Прикрепляет PDF КП к сделке в Bitrix24 в пользовательское поле файла.

        ВНИМАНИЕ: код поля UF_CRM_... нужно держать в синхронизации с Bitrix.
        Сейчас используется поле:
          - UF_CRM_1744862238040 — «Вложить Договор и Спецификацию»
        """
        # Поле пользовательского файла КП в сделке Bitrix24.
        # Проверено по deal 7753: именно UF_CRM_1744862238040 содержит offer_*.pdf.
        uf_field_code = "UF_CRM_1744862238040"

        try:
            if not pdf_path.exists():
                logger.error("attach_kp_pdf: файл %s не найден", pdf_path)
                return False

            # Используем прямой HTTP запрос через httpx, как в get_deal_comments,
            # потому что fast_bitrix24 не всегда корректно обрабатывает файлы в пользовательских полях.
            webhook = settings.BITRIX_WEBHOOK.rstrip("/")
            url = f"{webhook}/crm.deal.update.json"

            file_bytes = pdf_path.read_bytes()
            import base64
            file_base64 = base64.b64encode(file_bytes).decode("utf-8")

            async with httpx.AsyncClient(timeout=30) as client:
                # Bitrix24 REST API требует base64 формат для файлов в пользовательских полях.
                # Формат: fields[UF_CRM_...][fileData][0] = filename, fields[UF_CRM_...][fileData][1] = base64_content
                data = {
                    "id": str(deal_id),
                    f"fields[{uf_field_code}][fileData][0]": pdf_path.name,
                    f"fields[{uf_field_code}][fileData][1]": file_base64,
                }
                
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                result = resp.json()

            # Проверяем результат
            if result.get("result") is True or result.get("result") == {}:
                logger.info(
                    "Bitrix: к сделке %s прикреплён файл КП %s в поле %s",
                    deal_id,
                    pdf_path.name,
                    uf_field_code,
                )
                return True
            else:
                logger.error(
                    "Bitrix: ошибка прикрепления КП %s к сделке %s. Ответ: %s",
                    pdf_path.name,
                    deal_id,
                    result,
                )
                return False
        except Exception:
            logger.exception(
                "Bitrix: ошибка прикрепления КП %s к сделке %s",
                pdf_path,
                deal_id,
            )
            return False

    # ──────────────────────────────────────────────
    #  Компании (клиенты)
    # ──────────────────────────────────────────────

    async def get_company(self, company_id: int) -> Optional[Dict]:
        """Получает компанию по ID из Bitrix24."""
        from anyio import to_thread

        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.company.get",
                {"id": company_id},
            )
            
            # Обработка ответа аналогично get_deal
            if isinstance(result, dict):
                if "result" in result:
                    inner_result = result["result"]
                    if isinstance(inner_result, dict):
                        result = inner_result
                    elif isinstance(inner_result, list):
                        result = inner_result[0] if inner_result else None
                elif "ID" in result:
                    pass  # result уже правильный
                elif len(result) == 1:
                    only_value = next(iter(result.values()))
                    if isinstance(only_value, dict) and "ID" in only_value:
                        result = only_value
            
            if isinstance(result, dict) and "ID" in result:
                logger.info("Bitrix: получена компания id=%s", company_id)
                return result
            else:
                logger.warning("Bitrix: компания %s не найдена или неверный формат ответа", company_id)
                return None
        except Exception:
            logger.exception("Bitrix: ошибка получения компании %s", company_id)
            return None

    async def search_companies(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Поиск компаний в Bitrix24 по названию.

        query: строка, которую ввёл пользователь (начало названия, часть слова и т.п.)
        limit: максимальное количество результатов.
        """
        from anyio import to_thread

        try:
            # Используем get_all с фильтром по названию (частичное совпадение)
            result = await to_thread.run_sync(
                self.bx.get_all,
                "crm.company.list",
                {
                    "filter": {
                        "%TITLE": query,
                    },
                    "select": [
                        "ID",
                        "TITLE",
                        "PHONE",
                        "EMAIL",
                    ],
                    # Ограничиваем количество результатов на уровне кода
                },
            )

            companies = list(result) if result else []
            if limit and len(companies) > limit:
                companies = companies[:limit]

            logger.info(
                "Bitrix: найдено %d компаний по запросу '%s'",
                len(companies),
                query,
            )

            return companies
        except Exception:
            logger.exception("Bitrix: ошибка поиска компаний по запросу '%s'", query)
            return []

    async def search_users(self, name_query: str | None = None, email_query: str | None = None) -> List[Dict]:
        """
        Поиск пользователей в Bitrix24 по ФИО или Email.
        """
        from anyio import to_thread

        try:
            filter_dict = {}
            if email_query:
                filter_dict["EMAIL"] = email_query
            elif name_query:
                filter_dict["NAME"] = name_query
            else:
                return []

            result = await to_thread.run_sync(
                self.bx.get_all,
                "user.get",
                {
                    "filter": filter_dict,
                },
            )

            users = list(result) if result else []
            logger.info(
                "Bitrix: найдено %d пользователей по запросу (email='%s', name='%s')",
                len(users),
                email_query,
                name_query,
            )
            return users
        except Exception:
            logger.exception(
                "Bitrix: ошибка поиска пользователей по запросу (email='%s', name='%s')",
                email_query,
                name_query,
            )
            return []

    # ──────────────────────────────────────────────
    #  Контакты
    # ──────────────────────────────────────────────

    async def search_contacts(
        self,
        query: str,
        limit: int = 20,
        company_id: int | None = None,
    ) -> List[Dict]:
        """
        Поиск контактов в Bitrix24.

        query: строка поиска по имени/фамилии/отчеству.
        company_id: если указан — ищем только контакты этой компании.
        """
        try:
            filter_dict: Dict[str, object] = {
                "%NAME": query,
            }
            if company_id is not None:
                filter_dict["COMPANY_ID"] = company_id

            result = await to_thread.run_sync(
                self.bx.get_all,
                "crm.contact.list",
                {
                    "filter": filter_dict,
                    "select": [
                        "ID",
                        "NAME",
                        "LAST_NAME",
                        "SECOND_NAME",
                        "PHONE",
                        "EMAIL",
                        "COMPANY_ID",
                    ],
                },
            )

            contacts = list(result) if result else []
            if limit and len(contacts) > limit:
                contacts = contacts[:limit]

            logger.info(
                "Bitrix: найдено %d контактов по запросу '%s' (company_id=%s)",
                len(contacts),
                query,
                company_id,
            )

            return contacts
        except Exception:
            logger.exception(
                "Bitrix: ошибка поиска контактов по запросу '%s' (company_id=%s)",
                query,
                company_id,
            )
            return []

    # ──────────────────────────────────────────────
    #  Комментарии / Таймлайн сделки
    # ──────────────────────────────────────────────

    async def add_deal_comment(
        self, deal_id: int, text: str, author_id: int | None = None
    ) -> Optional[int]:
        """
        Добавляет комментарий в таймлайн сделки Bitrix24.
        
        Args:
            deal_id: ID сделки в Bitrix24
            text: Текст комментария
            author_id: ID пользователя Bitrix24, который оставляет комментарий (опционально)
        
        Returns:
            ID созданного комментария или None при ошибке
        """
        try:
            fields = {
                "ENTITY_ID": deal_id,
                "ENTITY_TYPE": "deal",
                "COMMENT": text,
            }
            
            # Если указан автор — добавляем его ID
            if author_id:
                fields["AUTHOR_ID"] = author_id
            
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.timeline.comment.add",
                {"fields": fields},
            )
            
            # fast_bitrix24 может вернуть ID напрямую или в обёртке
            comment_id = None
            if isinstance(result, (int, str)):
                comment_id = int(result)
            elif isinstance(result, dict):
                comment_id = int(result.get("result", result.get("ID", 0)))
            
            if comment_id:
                logger.info(
                    "Bitrix: комментарий добавлен к сделке %s, comment_id=%s, author_id=%s",
                    deal_id,
                    comment_id,
                    author_id,
                )
                return comment_id
            else:
                logger.warning(
                    "Bitrix: add_deal_comment вернул неожиданный формат: %s",
                    result,
                )
                return None
        except Exception:
            logger.exception(
                "Bitrix: ошибка добавления комментария к сделке %s",
                deal_id,
            )
            return None

    async def get_deal_comments(self, deal_id: int, limit: int = 50) -> List[Dict]:
        """
        Получает комментарии из таймлайна сделки Bitrix24.
        
        Args:
            deal_id: ID сделки в Bitrix24
            limit: Максимальное количество комментариев (по умолчанию 50)
        
        Returns:
            Список комментариев с полями: ID, CREATED, AUTHOR_ID, COMMENT, и т.д.
        """
        try:
            # Обходим fast_bitrix24 и вызываем REST Bitrix24 напрямую,
            # используя тот же формат, что и рабочий curl-запрос.
            webhook = settings.BITRIX_WEBHOOK.rstrip("/")
            url = f"{webhook}/crm.timeline.comment.list.json"

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    url,
                    params={
                        "filter[ENTITY_ID]": deal_id,
                        "filter[ENTITY_TYPE]": "deal",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            logger.info(
                "Bitrix: raw response for crm.timeline.comment.list deal_id=%s: %s",
                deal_id,
                data,
            )

            raw = data.get("result", [])
            comments: List[Dict] = raw if isinstance(raw, list) else []

            # Сортируем по времени создания, чтобы UI/ТМА стабильно показывали новые сообщения сверху.
            # В Bitrix обычно поле CREАTED в ISO-формате, по нему можно сортировать лексикографически.
            comments.sort(key=lambda c: c.get("CREATED") or c.get("DATE_CREATE") or "", reverse=True)

            # Ограничиваем количество
            if limit and len(comments) > limit:
                comments = comments[:limit]
            
            logger.info(
                "Bitrix: получено %d комментариев для сделки %s",
                len(comments),
                deal_id,
            )
            
            return comments
        except Exception:
            logger.exception(
                "Bitrix: ошибка получения комментариев сделки %s",
                deal_id,
            )
            # Возвращаем пустой список вместо None, чтобы фронт не падал
            return []

    # ──────────────────────────────────────────────
    #  Встроенный чат сделки (Bitrix24 IM)
    # ──────────────────────────────────────────────

    async def _im_rest_call(self, method: str, data: Dict[str, object]) -> Dict:
        """
        Вызов методов Bitrix24 REST напрямую (через httpx).
        Нужен, т.к. fast_bitrix24/typed методы могут не покрывать IM полностью.
        """
        webhook = settings.BITRIX_WEBHOOK.rstrip("/")
        url = f"{webhook}/{method}.json"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=data)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                # Текст ответа нужен, чтобы быстро понять: неверные параметры / нет прав / метод недоступен.
                logger.error(
                    "Bitrix IM REST error: method=%s status=%s body=%s",
                    method,
                    resp.status_code,
                    resp.text,
                )
                raise

            payload = resp.json()

            # Bitrix иногда возвращает ошибку в JSON даже при HTTP 200.
            if isinstance(payload, dict) and (
                "error" in payload or "error_description" in payload
            ):
                logger.error(
                    "Bitrix IM REST API returned error: method=%s status=%s payload=%s",
                    method,
                    resp.status_code,
                    payload,
                )
                raise RuntimeError(
                    f"Bitrix IM REST error for {method}: {payload.get('error') or payload.get('error_description')}"
                )

            return payload

    async def ensure_deal_chat_dialog_id(
        self,
        deal_id: int,
    ) -> int | None:
        """
        Создаёт/привязывает IM-чат к CRM-сделке и возвращает DIALOG_ID.

        Используем метод `im.chat.crm.add`, который связывает чат с сущностью сделки.
        """
        payload: Dict[str, object] = {
            # Параметры REST обычно ожидаются напрямую.
            # (Если твоя инсталляция требует иной формат — увидим это в ошибке.)
            "ENTITY_TYPE": "CRM",
            "ENTITY_ID": str(deal_id),
        }

        data = await self._im_rest_call("im.chat.crm.add", payload)
        result = data.get("result", data) if isinstance(data, dict) else data

        if isinstance(result, dict):
            dialog_id = result.get("DIALOG_ID") or result.get("dialogId")
            if dialog_id is not None:
                return int(dialog_id)

            chat_id = result.get("CHAT_ID") or result.get("chatId")
            if chat_id is not None:
                return int(chat_id)

        raise RuntimeError(
            f"Bitrix IM: im.chat.crm.add did not return DIALOG_ID/CHAT_ID. Raw response: {data}"
        )

    async def send_deal_chat_message(
        self,
        deal_id: int,
        *,
        author_id: int | None,
        text: str,
    ) -> int | None:
        """
        Отправляет сообщение в IM-чат, привязанный к сделке.
        Возвращает MESSAGE_ID (если Bitrix вернёт).
        """
        try:
            # 1) Пытаемся отправить в IM-диалог (если методы доступны)
            dialog_id = await self.ensure_deal_chat_dialog_id(deal_id=deal_id)
            payload: Dict[str, object] = {
                "DIALOG_ID": str(dialog_id),
                "MESSAGE": text,
            }
            if author_id:
                payload["AUTHOR_ID"] = str(author_id)

            data = await self._im_rest_call("im.message.add", payload)
            result = data.get("result", data) if isinstance(data, dict) else data

            if isinstance(result, dict):
                message_id = result.get("MESSAGE_ID") or result.get("messageId") or result.get("ID") or result.get("id")
                if message_id is not None:
                    return int(message_id)
            raise RuntimeError(f"Bitrix IM: im.message.add did not return MESSAGE_ID. Raw response: {data}")
        except Exception as e:
            # 2) Если IM в Bitrix24 не поддерживается (например, ERROR_METHOD_NOT_FOUND) — fallback в timeline-комментарии.
            if self._im_not_supported_error(e):
                logger.warning(
                    "Bitrix IM не поддерживается в этой инсталляции: fallback to timeline comment. deal_id=%s, err=%s",
                    deal_id,
                    e,
                )
                comment_id = await self.add_deal_comment(deal_id=deal_id, text=text, author_id=author_id)
                return comment_id

            logger.exception(
                "Bitrix IM: ошибка отправки сообщения в deal chat (deal_id=%s).",
                deal_id,
            )
            raise

    async def get_deal_chat_messages(
        self,
        deal_id: int,
        *,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Получает сообщения из IM-диалога, привязанного к сделке.
        """
        try:
            dialog_id = await self.ensure_deal_chat_dialog_id(deal_id=deal_id)

            payload: Dict[str, object] = {"DIALOG_ID": str(dialog_id)}
            data = await self._im_rest_call("im.dialog.get", payload)

            result = data.get("result", data) if isinstance(data, dict) else data
            messages = []
            if isinstance(result, dict):
                raw_msgs = result.get("messages") or result.get("MESSAGE_LIST") or []
                if isinstance(raw_msgs, list):
                    messages = raw_msgs

            if limit and len(messages) > limit:
                messages = messages[:limit]

            return messages
        except Exception as e:
            if self._im_not_supported_error(e):
                logger.warning(
                    "Bitrix IM не поддерживается (get_deal_chat_messages): fallback to timeline comment list. deal_id=%s, err=%s",
                    deal_id,
                    e,
                )
                return await self.get_deal_comments(deal_id=deal_id, limit=limit)

            payload: Dict[str, object] = {"DIALOG_ID": str(dialog_id)}
            logger.exception("Bitrix IM: ошибка получения сообщений deal_id=%s.", deal_id)
            return []
