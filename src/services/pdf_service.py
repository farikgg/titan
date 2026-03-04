from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parents[2]
MEDIA_DIR = BASE_DIR / "media"
FONTS_DIR = BASE_DIR / "fonts"


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
        # Шапка компании (как в примере КП)
        # ----------------------------------------
        c.setFont("Arial", 9)
        left_x = 20 * mm
        top_y = height - 20 * mm

        header_lines = [
            "Қазақстан Республикасы",
            "Нур-Султан қаласы, Есіл а.",
            "Діимұхамед Қонаев к-сі 33, 1003 кеңсе",
            "Тел.: 8 (7172) 50-19-34, 8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
            "",
            "ТИТАН",
            "ТОРГОВО-ПРОМЫШЛЕННАЯ ГРУППА",
            "Республика Казахстан, г.Нур-Султан, район Есиль, ул. Діимұхамед Қонаев, здание 33, офис 1003",
            "Тел.: 8 (7172) 50-19-34, 8 (7172) 50-19-31",
            "e-mail: titan_astana@mail.ru",
            "www.tpgt.kz",
        ]

        y = top_y
        for line in header_lines:
            c.drawString(left_x, y, line)
            y -= 4.5 * mm

        # ----------------------------------------
        # Номер и дата КП
        # ----------------------------------------
        c.setFont("Arial", 10)
        kp_number = f"КП №{deal['id']}"
        date_str = datetime.now().strftime("от %d %B %Y г.")

        y -= 4 * mm
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

        col_widths = [
            10 * mm,  # №
            70 * mm,  # Товары
            18 * mm,  # Кол-во
            18 * mm,  # Ед. изм.
            25 * mm,  # Цена
            30 * mm,  # Сумма
            25 * mm,  # Срок поставки
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
