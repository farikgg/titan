from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parents[2]
MEDIA_DIR = BASE_DIR / "media"
FONTS_DIR = BASE_DIR / "fonts"

class PdfService:
    def generate_offer(self, deal: dict) -> Path:
        MEDIA_DIR.mkdir(exist_ok=True)

        font_path = FONTS_DIR / "Arial.ttf"
        pdfmetrics.registerFont(TTFont("Arial", str(font_path)))

        path = MEDIA_DIR / f"offer_{deal['id']}.pdf"

        c = canvas.Canvas(str(path), pagesize=A4)

        c.setFont("Arial", 14)
        c.drawString(20 * mm, 280 * mm, "Коммерческое предложение")

        c.setFont("Arial", 10)
        c.drawString(20 * mm, 270 * mm, f"Сделка: {deal['title']}")
        c.drawString(20 * mm, 262 * mm, f"Дата: {datetime.now():%d.%m.%Y}")

        y = 250 * mm
        for item in deal.get("items", []):
            c.drawString(20 * mm, y, f"{item['art']} | {item['price']} {deal['currency']} | {item['quantity']} - {item['total']} {deal['currency']}")
            y -= 8 * mm
            if y < 20 * mm:
                c.showPage()
                y = 270 * mm

        c.save()
        return path
