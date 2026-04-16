import logging
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.schemas.price_schema import PriceCreate, PriceRead
from src.services.price_service import PriceService
from src.core.rbac import require_permission
from src.repositories.analog_repo import AnalogRepository
from src.services.fuchs_price_report_service import FuchsPriceReportService
from src.integrations.azure.outlook_client import OutlookClient
from src.core.graph_auth import GraphAuth
from src.app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prices", tags=["Prices"])
price_service = PriceService()
analog_repo = AnalogRepository()


# ──────────────────────────────────────────────
#  Базовые CRUD (существующие)
# ──────────────────────────────────────────────

@router.post(
    "/",
    response_model=PriceRead,
    dependencies=[Depends(require_permission("prices.write"))],
)
async def create_price(
    price_in: PriceCreate,
    db: AsyncSession = Depends(get_db),
):
    return await price_service.add_new_price(db, price_in)


@router.get(
    "/",
    response_model=list[PriceRead],
    dependencies=[Depends(require_permission("prices.read"))],
)
async def get_all_prices(
    db: AsyncSession = Depends(get_db),
):
    return await price_service.get_prices_list(db)


@router.get(
    "/search/{art}",
    response_model=PriceRead,
    dependencies=[Depends(require_permission("prices.read"))],
)
async def search_single(
    art: str,
    db: AsyncSession = Depends(get_db),
):
    return await price_service.get_price(db, art)


# ──────────────────────────────────────────────
#  Excel Export
# ──────────────────────────────────────────────

@router.get(
    "/export",
    dependencies=[Depends(require_permission("prices.read"))],
    summary="Скачать Excel отчёт по ценам FUCHS (статусы + unit price)",
)
async def export_prices_excel(
    db: AsyncSession = Depends(get_db),
):
    """
    Генерирует и возвращает Excel файл с ценами FUCHS.
    Листы: expired / expiring_soon / all / analogs
    """
    report_service = FuchsPriceReportService(expiring_days_threshold=7)

    output_dir = Path("/tmp/titan_reports")
    out_path = await report_service.build_report_xlsx(db, output_dir=output_dir)

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ──────────────────────────────────────────────
#  Аналоги товаров
# ──────────────────────────────────────────────

class AnalogResponse(BaseModel):
    id: int
    source_art: str
    analog_art: str
    analog_name: str | None = None
    analog_source: str | None = None
    notes: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AddAnalogRequest(BaseModel):
    analog_art: str
    analog_name: str | None = None
    analog_source: str | None = None
    notes: str | None = None


@router.get(
    "/{art}/analogs",
    response_model=list[AnalogResponse],
    dependencies=[Depends(require_permission("prices.read"))],
    summary="Получить аналоги товара",
)
async def get_analogs(
    art: str,
    db: AsyncSession = Depends(get_db),
):
    return await analog_repo.get_by_source_art(db, art.strip().upper())


@router.post(
    "/{art}/analogs",
    response_model=AnalogResponse,
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Добавить аналог товара",
)
async def add_analog(
    art: str,
    body: AddAnalogRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        analog = await analog_repo.create(
            db,
            source_art=art.strip().upper(),
            analog_art=body.analog_art.strip().upper(),
            analog_name=body.analog_name,
            analog_source=body.analog_source,
            notes=body.notes,
        )
        await db.commit()
        return analog
    except Exception as e:
        await db.rollback()
        if "uq_analog_pair" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"Аналог {body.analog_art} уже существует для товара {art}",
            )
        raise


@router.delete(
    "/analogs/{analog_id}",
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Удалить аналог",
)
async def delete_analog(
    analog_id: int,
    db: AsyncSession = Depends(get_db),
):
    deleted = await analog_repo.delete_by_id(db, analog_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Аналог не найден")
    await db.commit()
    return {"deleted": True, "id": analog_id}


# ──────────────────────────────────────────────
#  Ретро-пересчёт unit_price
# ──────────────────────────────────────────────

@router.post(
    "/recalculate-unit-prices",
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Пересчитать unit_price для всех записей в БД",
)
async def recalculate_unit_prices(
    db: AsyncSession = Depends(get_db),
):
    """
    Ретро-расчёт: для всех PriceModel, где есть container_size,
    пересчитывает unit_price и unit_measure.
    """
    from src.db.models.price_model import PriceModel
    from sqlalchemy import select

    result = await db.execute(select(PriceModel))
    prices = list(result.scalars().all())

    updated = 0
    flagged = 0
    for p in prices:
        if p.container_size and p.price:
            unit_price, unit_measure = PriceService.calculate_unit_price(
                p.price, p.container_size, p.container_unit
            )
            if unit_price != p.unit_price or unit_measure != p.unit_measure:
                p.unit_price = unit_price
                p.unit_measure = unit_measure
                p.unit_price_missing = False
                updated += 1
        elif p.price and not p.container_size:
            if not p.unit_price_missing:
                p.unit_price_missing = True
                flagged += 1

    await db.commit()
    return {
        "total": len(prices),
        "updated": updated,
        "flagged_missing": flagged,
    }


@router.post(
    "/{art}/request-analog",
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Отправить запрос на поиск аналога (Email)",
)
async def request_analog_email(
    art: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Находит товар по артикулу.
    1. Сначала ищет подтверждённый аналог в БД.
    2. Если найден — возвращает его без отправки email.
    3. Если не найден — отправляет Email-запрос поставщику.
    """
    price_obj = await price_service.get_price(db, art)
    if not price_obj:
        raise HTTPException(status_code=404, detail=f"Product with art {art} not found")

    # --- ПРОВЕРКА БД АНАЛОГОВ ---
    analogs = await analog_repo.get_all_for_product(db, art, price_obj.name)
    confirmed = [a for a in analogs if a.status == "confirmed"]

    if len(confirmed) == 1:
        a = confirmed[0]
        return {
            "status": "analog_found",
            "source": "db",
            "analog_code": a.analog_product_code,
            "analog_name": a.analog_product_name,
            "analog_brand": a.analog_brand,
            "confidence_level": a.confidence_level,
        }

    if len(confirmed) > 1:
        return {
            "status": "multiple_analogs",
            "source": "db",
            "analogs": [
                {
                    "analog_code": a.analog_product_code,
                    "analog_name": a.analog_product_name,
                    "analog_brand": a.analog_brand,
                    "confidence_level": a.confidence_level,
                }
                for a in confirmed
            ],
        }

    # --- АНАЛОГ НЕ НАЙДЕН → EMAIL ---
    auth = GraphAuth()
    client = OutlookClient(auth)

    # Адрес получателя (из настроек)
    to_email = settings.ANALOG_REQUEST_RECIPIENT
    subject = f"Запрос аналога: {price_obj.name} (art: {price_obj.art})"
    
    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; border: 1px solid #eee; padding: 20px;">
        <h2 style="color: #004a99; border-bottom: 2px solid #004a99; padding-bottom: 10px;">Запрос на поиск аналога</h2>
        <p>Приветствую, <b>Евгений</b>!</p>
        <p>Для подготовки коммерческого предложения менеджеру требуется подобрать аналог для следующей позиции:</p>
        
        <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
            <tr style="background-color: #f9f9f9;">
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Товар:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;">{price_obj.name}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Артикул:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;"><code>{price_obj.art}</code></td>
            </tr>
            <tr style="background-color: #f9f9f9;">
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Бренд / Источник:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;">{price_obj.source.value if price_obj.source else "Не указан"}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Тара:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;">{price_obj.container_size or "---"} {price_obj.container_unit or ""}</td>
            </tr>
        </table>
        
        <p style="margin-top: 25px; font-size: 0.9em; color: #666;">
            Пожалуйста, проверьте наличие альтернатив и сообщите ответному менеджеру.
        </p>
        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;"/>
        <p style="font-size: 0.8em; color: #999;"><i>Отправлено автоматически из Titan Automation System</i></p>
    </div>
    """

    await client.send_email(to_email=to_email, subject=subject, body=body)
    
    return {"status": "request_sent", "to": to_email}


@router.post(
    "/analog-requests/{request_id}/send-email",
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Отправить запрос на поиск аналога (Email) для блокирующей позиции",
)
async def send_analog_request_email(
    request_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Отправляет Email-запрос на поиск аналога для записи из AnalogRequestModel.
    Используется для позиций, которых нет в прайсе.
    """
    from src.db.models.analog_request_model import AnalogRequestModel
    from sqlalchemy import select
    from datetime import datetime

    request_obj = await db.scalar(
        select(AnalogRequestModel).where(AnalogRequestModel.id == request_id)
    )
    if not request_obj:
        raise HTTPException(status_code=404, detail=f"Analog request {request_id} not found")

    auth = GraphAuth()
    client = OutlookClient(auth)

    to_email = settings.ANALOG_REQUEST_RECIPIENT
    product_display = request_obj.product_name or request_obj.product_code or f"ID:{request_id}"
    subject = f"СРОЧНЫЙ ЗАПРОС АНАЛОГА: {product_display}"
    
    # Формируем HTML тело письма
    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; border: 1px solid #eee; padding: 20px;">
        <h2 style="color: #d32f2f; border-bottom: 2px solid #d32f2f; padding-bottom: 10px;">Запрос на подбор аналога</h2>
        <p>Приветствую, <b>Евгений</b>!</p>
        <p>В системе зафиксирована позиция, требующая ручного подбора аналога (отсутствует в текущих прайсах):</p>
        
        <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
            <tr style="background-color: #f9f9f9;">
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Наименование:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;">{request_obj.product_name or "---"}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Артикул:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;"><code>{request_obj.product_code or "---"}</code></td>
            </tr>
            <tr style="background-color: #f9f9f9;">
                <td style="padding: 10px; border: 1px solid #ddd;"><b>Бренд / Поставщик:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;">{request_obj.brand or "---"} / {request_obj.supplier or "---"}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #ddd;"><b>ID Сделки:</b></td>
                <td style="padding: 10px; border: 1px solid #ddd;">#{request_obj.deal_id or "---"}</td>
            </tr>
        </table>
        
        <p style="margin-top: 25px; font-size: 0.9em; color: #666;">
            Пожалуйста, подберите подходящий аналог и внесите его в базу данных Титан или ответьте на этот запрос.
        </p>
        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;"/>
        <p style="font-size: 0.8em; color: #999;"><i>Отправлено автоматически из Titan Automation System</i></p>
    </div>
    """

    try:
        result = await client.send_email(to_email=to_email, subject=subject, body=body)
        
        # Обновляем статус в БД
        request_obj.request_status = "sent"
        request_obj.sent_at = datetime.now()
        request_obj.email_thread_id = result.get("conversationId")
        await db.commit()
        
        return {"status": "success", "request_id": request_id, "sent_to": to_email}
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to send analog search email")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")
