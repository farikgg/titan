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
        current_top_y = height - top_margin

        logo_path = MEDIA_DIR / LOGO_FILENAME
        if logo_path.exists():
            # Высота логотипа на странице (подогнано под пример)
            logo_height = 22 * mm
            logo = ImageReader(str(logo_path))
            img_width, img_height = logo.getSize()
            aspect = img_width / float(img_height or 1)
            logo_width = logo_height * aspect

            logo_x = (width - logo_width) / 2  # по центру страницы
            logo_y = current_top_y - logo_height

            c.drawImage(
                logo,
                logo_x,
                logo_y,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask="auto",
            )

            # Опускаем текстовую шапку чуть ниже логотипа
            current_top_y = logo_y - 4 * mm

        # ----------------------------------------
        # Шапка компании (контактные данные), как в примере КП
        # ----------------------------------------
        c.setFont("Arial", 9)
        top_y = current_top_y

        # Левый блок (казахский адрес)
        left_header_lines = [
            "Қазақстан Республикасы",
            "Нур-Султан қаласы, Есіл а.",
            "Діимұхамед Қонаев к-сі 33, 1003 кеңсе",
            "Тел.: 8 (7172) 50-19-34, 8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
        ]

        # Правый блок (русский адрес), выравниваем по правому краю
        right_header_lines = [
            "Республика Казахстан, г.Нур-Султан, район Есиль,",
            "ул. Діимұхамед Қонаев, здание 33, офис 1003",
            "Тел.: 8 (7172) 50-19-34, 8 (7172) 50-19-31",
            "e-mail: titan_astана@mail.ru",
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
        # Номер и дата КП
        # ----------------------------------------
        c.setFont("Arial", 10)
        kp_number = f"КП №{deal['id']}"
        date_str = datetime.now().strftime("от %d %B %Y г.")

        y -= 6 * mm
        c.drawString(left_x, y, kp_number + " " + date_str)

        # ----------------------------------------
        # Заголовок КП и предмет
        # ----------------------------------------
        y -= 10 * mm
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

        table_data = [
            [
                "№",
                "Товары\n(работы/услуги)",
                "Кол-во",
                "Ед. изм.",
                "Цена, евро\n(без НДС)",
                "Сумма, евро\n(без НДС)",
                "Срок\nпоставки",
            ]
        ]

        total_sum = 0.0
        currency = deal.get("currency") or "евро"

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
        col_widths = [
            10 * mm,  # №
            70 * mm,  # Товары
            15 * mm,  # Кол-во
            15 * mm,  # Ед. изм.
            25 * mm,  # Цена
            25 * mm,  # Сумма
            10 * mm,  # Срок поставки
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

        conditions = [
            "Условия оплаты: пост оплата 30 дней после оеврорузки продукции",
            "Условия поставки: DDP склад Покупателя",
            "Гарантийный срок: 12 месяцев (при надлежащих условиях хранения)",
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

        c.save()
        return path
