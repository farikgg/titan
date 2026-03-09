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

        logo_path = MEDIA_DIR / LOGO_FILENAME
        if logo_path.exists():
            # Высота логотипа на странице (подогнано под пример)
            logo_height = 22 * mm
            logo = ImageReader(str(logo_path))
            img_width, img_height = logo.getSize()
            aspect = img_width / float(img_height or 1)
            logo_width = logo_height * aspect

            # Координаты логотипа: по центру страницы
            logo_x = (width - logo_width) / 2
            logo_y = height - top_margin - logo_height

            c.drawImage(
                logo,
                logo_x,
                logo_y,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask="auto",
            )

            # Центр логотипа по вертикали
            logo_center_y = logo_y + logo_height / 2

            # Текстовые блоки (слева и справа) выравниваем по высоте середины логотипа
            # Маленький сдвиг вверх, чтобы визуально смотрелось аккуратно
            top_y_for_header = logo_center_y + 1 * mm

        # ----------------------------------------
        # Шапка компании (контактные данные), как в примере КП
        # ----------------------------------------
        c.setFont("Arial", 9)
        top_y = top_y_for_header

        # Левый блок (казахский адрес)
        left_header_lines = [
            "Қазақстан Республикасы",
            "Нур-Султан қаласы, Есіл а.",
            "Дінмұхамед Қонаев к-сі 33, 1003 кеңсе",
            "Тел.: 8 (7172) 50-19-34, 8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
        ]

        # Правый блок (русский адрес), выравниваем по правому краю
        right_header_lines = [
            "Республика Казахстан, г.Нур-Султан, район Есиль,",
            "ул. Дінмұхамед Қонаев, здание 33, офис 1003",
            "Тел.: 8 (7172) 50-19-34, 8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
        ]

        # Левый столбец
        y_left = top_y
        for line in left_header_lines:
            c.drawString(left_x, y_left, line)
            y_left -= 4.0 * mm

        # Правый столбец
        right_x = width - left_x
        y_right = top_y
        for line in right_header_lines:
            c.drawRightString(right_x, y_right, line)
            y_right -= 4.0 * mm

        # Горизонтальная линия под шапкой
        y_after_header = min(y_left, y_right) - 3 * mm
        c.setLineWidth(0.7)
        c.line(15 * mm, y_after_header, width - 15 * mm, y_after_header)

        y = y_after_header

        # ----------------------------------------
        # Заголовок КП и предмет
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

        # Предмет КП: берём название первого товара, если есть
        items = deal.get("items", [])
        subject = ""
        if items:
            first_name = items[0].get("name") or ""
            subject = f"на {first_name}"

        if subject:
            y -= 8 * mm
            c.setFont("Arial", 10)
            c.drawString(left_x, y, subject)

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

        table_data = [
            [
                "№",
                "Товары\n(работы/услуги)",
                "Кол-во",
                "Ед. изм.",
                f"Цена, {currency_label}\n(без НДС)",
                f"Сумма, {currency_label}\n(без НДС)",
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

        # Динамические условия с дефолтами
        payment_terms = deal.get(
            "payment_terms",
            "Условия оплаты: постоплата 30 дней после отгрузки продукции",
        )
        delivery_terms = deal.get(
            "delivery_terms",
            "Условия поставки: DDP склад Покупателя",
        )
        warranty_terms = deal.get(
            "warranty_terms",
            "Гарантийный срок: 12 месяцев (при надлежащих условиях хранения)",
        )

        conditions = [
            payment_terms,
            delivery_terms,
            warranty_terms,
        ]

        for line in conditions:
            c.drawString(left_x, footer_y, line)
            footer_y -= 5 * mm

        # ----------------------------------------
        # Подписи
        # ----------------------------------------
        footer_y -= 10 * mm
        c.setFont("Arial", 10)
        c.drawString(left_x, footer_y, "Директор")
        c.drawString(left_x + 40 * mm, footer_y, 'ТОО «ТПГ «Титан»')
        c.drawString(left_x + 95 * mm, footer_y, "Бухановский Е.С.")

        # Блок контактной информации менеджера (если передана)
        manager_name = deal.get("manager_name") or ""
        manager_phone = deal.get("manager_phone") or ""
        if manager_name or manager_phone:
            footer_y -= 8 * mm
            c.setFont("Arial", 9)
            text = "Менеджер: " + manager_name
            if manager_phone:
                text += f", тел.: {manager_phone}"
            c.drawString(left_x, footer_y, text)

        c.save()
        return path
