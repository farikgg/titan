from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parents[2]
MEDIA_DIR = BASE_DIR / "media"
FONTS_DIR = BASE_DIR / "fonts"
LOGO_FILENAME = "titan_logo.png"  # файл логотипа, который нужно положить в папку media


class PdfService:
    def generate_offer(self, deal: dict) -> Path:
        """
        Генерация КП в стиле шаблона «КП №... от ... г.» для ТПГ «Титан».
        """
        MEDIA_DIR.mkdir(exist_ok=True)

        font_path = FONTS_DIR / "Arial.ttf"
        pdfmetrics.registerFont(TTFont("Arial", str(font_path)))

        path = MEDIA_DIR / f"offer_{deal['id']}.pdf"

        c = canvas.Canvas(str(path), pagesize=A4)
        width, height = A4

        # ----------------------------------------
        # Логотип по центру шапки
        # ----------------------------------------
        left_x = 20 * mm
        top_margin = 20 * mm
        top_y_for_header = height - top_margin

        # ----------------------------------------
        # Шапка компании (контактные данные), как в примере КП
        # ----------------------------------------
        c.setFont("Arial", 9)
        
        # Левый блок (казахский адрес)
        left_header_lines = [
            "Қазақстан Республикасы",
            "Нур-Султан қаласы, Есіл а.",
            "Дінмұхамед Қонаев к-сі 33, 1003 кеңсе",
            "Тел.: 8 (7172) 50-19-34,",
            "8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
        ]

        # Правый блок (русский адрес), выравниваем по правому краю
        right_header_lines = [
            "Республика Казахстан, г.Нур-Султан,",
            "район Есиль, ул. Дінмұхамед Қонаев,",
            "здание 33, офис 1003",
            "Тел.: 8 (7172) 50-19-34,",
            "8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
        ]

        # Определяем высоту строки "Дінмұхамед Қонаев к-сі 33, 1003 кеңсе" (3-я строка, индекс 2)
        # Сначала задаём начальную позицию текста (примерно)
        line_spacing = 4.0 * mm
        target_line_index = 2  # Индекс строки "Дінмұхамед Қонаев к-сі 33, 1003 кеңсе"
        
        # Предварительная позиция для текста (будет скорректирована после расчёта логотипа)
        initial_text_y = height - top_margin - 15 * mm
        
        logo_path = MEDIA_DIR / LOGO_FILENAME
        if logo_path.exists():
            # Высота логотипа на странице (уменьшена в 1.5 раза: было 22mm, стало ~14.67mm)
            logo_height = 22 * mm / 1.5
            logo = ImageReader(str(logo_path))
            img_width, img_height = logo.getSize()
            aspect = img_width / float(img_height or 1)
            logo_width = logo_height * aspect

            # Вычисляем, где должна быть строка "Дінмұхамед Қонаев к-сі 33, 1003 кеңсе"
            # Если top_y - позиция первой строки, то 3-я строка будет на top_y - 2 * line_spacing
            # Центр логотипа должен совпадать с этой высотой
            target_line_y = initial_text_y - target_line_index * line_spacing
            
            # Центр логотипа должен быть на уровне target_line_y
            logo_center_y = target_line_y
            logo_y = logo_center_y - logo_height / 2

            # Координаты логотипа: по центру страницы по горизонтали
            logo_x = (width - logo_width) / 2

            c.drawImage(
                logo,
                logo_x,
                logo_y,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask="auto",
            )

            # Теперь вычисляем top_y для текста так, чтобы 3-я строка была на уровне центра логотипа
            # target_line_y = top_y - target_line_index * line_spacing
            # logo_center_y = target_line_y
            # Значит: top_y = logo_center_y + target_line_index * line_spacing
            top_y = logo_center_y + target_line_index * line_spacing
        else:
            # Если логотипа нет, используем стандартную позицию
            top_y = initial_text_y

        # Левый столбец
        y_left = top_y
        for line in left_header_lines:
            c.drawString(left_x, y_left, line)
            y_left -= line_spacing

        # Правый столбец
        right_x = width - left_x
        y_right = top_y
        for line in right_header_lines:
            c.drawRightString(right_x, y_right, line)
            y_right -= line_spacing

        # Горизонтальная линия под шапкой
        y_after_header = min(y_left, y_right) - 3 * mm
        c.setLineWidth(0.7)
        c.line(15 * mm, y_after_header, width - 15 * mm, y_after_header)

        y = y_after_header

        # ----------------------------------------
        # Заголовок КП (без жёстко прошитого названия товара)
        # ----------------------------------------
        y -= 10 * mm
        # Форматируем дату вручную по-русски, чтобы не зависеть от локали ОС
        now = datetime.now()
        month_names = {
            1: "января",
            2: "февраля",
            3: "марта",
            4: "апреля",
            5: "мая",
            6: "июня",
            7: "июля",
            8: "августа",
            9: "сентября",
            10: "октября",
            11: "ноября",
            12: "декабря",
        }
        month_name = month_names.get(now.month, "")
        date_str = f"от {now.day:02d} {month_name} {now.year} г."
        title = f"КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ №{deal['id']} {date_str}"
        c.setFont("Arial", 12)
        c.drawString(left_x, y, title)

        # Раньше здесь выводили строку вида "на RENOLIT CX-EP 2" (название первого товара).
        # По новым требованиям не указываем конкретного клиента/товар в заголовке,
        # поэтому блок с subject убран. При необходимости можно добавить
        # нейтральную формулировку вроде "на поставку продукции".

        items = deal.get("items", [])

        # ----------------------------------------
        # Таблица товаров в стиле примера
        # ----------------------------------------
        y -= 12 * mm

        # Определяем человекочитаемое название валюты для заголовков
        currency_code = (deal.get("currency") or "").upper()
        currency_names = {
            "EUR": "евро",
            "USD": "доллар США",
            "RUB": "руб.",
            "KZT": "тенге",
        }
        currency_label = currency_names.get(currency_code, currency_code or "валюта")

        # Флаг НДС: если включён, убираем подпись «без НДС» из заголовка
        vat_enabled = bool(deal.get("vat_enabled"))
        if vat_enabled:
            price_header = f"Цена, {currency_label}"
            total_header = f"Сумма, {currency_label}"
        else:
            price_header = f"Цена, {currency_label}\n(без НДС)"
            total_header = f"Сумма, {currency_label}\n(без НДС)"

        table_data = [
            [
                "№",
                "Товары\n(работы/услуги)",
                "Кол-во",
                "Ед. изм.",
                price_header,
                total_header,
                "Срок\nпоставки",
            ]
        ]

        total_sum = 0.0

        for idx, item in enumerate(items, start=1):
            qty = item.get("quantity", 0)
            price = float(item.get("price", 0) or 0)
            total = float(item.get("total", price * qty) or 0)
            total_sum += total

            name = item.get("name") or ""
            art = item.get("art") or ""
            full_name = f"{name} ({art})" if art else name

            row = [
                str(idx),
                full_name,
                str(qty),
                "шт.",
                f"{price:,.2f}".replace(",", " "),
                f"{total:,.2f}".replace(",", " "),
                "",  # срок поставки — при необходимости можно добавить из item
            ]
            table_data.append(row)

        # Итоговая строка
        table_data.append(
            [
                "",
                "Итого:",
                "",
                "",
                "",
                f"{total_sum:,.2f}".replace(",", " "),
                "",
            ]
        )

        # Ширина страницы A4 ≈ 210 мм, при левом отступе 20 мм оставляем
        # рабочую область ~170 мм под таблицу, чтобы она не выходила за рамки.
        # Немного перераспределяем ширину в пользу последней колонки.
        col_widths = [
            8 * mm,   # №
            68 * mm,  # Товары
            14 * mm,  # Кол-во
            14 * mm,  # Ед. изм.
            24 * mm,  # Цена
            28 * mm,  # Сумма
            14 * mm,  # Срок поставки
        ]

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Arial"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("FONTSIZE", (0, 1), (-1, -2), 8),
                    ("FONTSIZE", (0, -1), (-1, -1), 9),
                    ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("ALIGN", (2, 1), (6, -2), "CENTER"),
                    ("ALIGN", (5, -1), (5, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ]
            )
        )

        table_width, table_height = table.wrap(0, 0)
        table_y = max(40 * mm, y - table_height)
        table.drawOn(c, left_x, table_y)

        # ----------------------------------------
        # Условия (ниже таблицы)
        # ----------------------------------------
        footer_y = table_y - 15 * mm
        c.setFont("Arial", 9)

        # Динамические условия с дефолтами.
        # Важно: deal может содержать None, поэтому используем "or" для подстановки строки.
        payment_terms = deal.get("payment_terms") or (
            "Условия оплаты: постоплата 30 дней после отгрузки продукции"
        )
        delivery_terms = deal.get("delivery_terms") or (
            "Условия поставки: DDP склад Покупателя"
        )
        warranty_terms = deal.get("warranty_terms") or (
            "Гарантийный срок: 12 месяцев (при надлежащих условиях хранения)"
        )

        conditions = [
            payment_terms,
            delivery_terms,
            warranty_terms,
        ]

        for line in conditions:
            # На всякий случай защищаемся от нестроковых значений / None
            text = str(line) if line is not None else ""
            if not text:
                continue
            c.drawString(left_x, footer_y, text)
            footer_y -= 5 * mm

        # ----------------------------------------
        # Подписи
        # ----------------------------------------
        footer_y -= 10 * mm
        c.setFont("Arial", 10)

        # Левый блок: должность + организация
        c.drawString(left_x, footer_y, "Директор ТОО «ТПГ «Титан»")

        # Правый блок: ФИО директора, выровненное по правому краю
        right_x = width - left_x
        c.drawRightString(right_x, footer_y, "Бухановский Е.С.")

        # Имя / телефон менеджера по требованию заказчика временно не выводим,
        # чтобы КП было более универсальным и не зависело от конкретного сотрудника.

        c.save()
        return path
