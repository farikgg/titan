from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from pathlib import Path
from datetime import datetime


class PdfService:
    def generate_offer(self, deal: dict) -> Path:
        path = Path(f"/tmp/offer_{deal['id']}.pdf")
        c = canvas.Canvas(str(path), pagesize=A4)

        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, 280 * mm, "Коммерческое предложение")

        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, 270 * mm, f"Сделка: {deal['title']}")
        c.drawString(20 * mm, 262 * mm, f"Дата: {datetime.now():%d.%m.%Y}")

        y = 250 * mm
        for item in deal.get("items", []):
            c.drawString(20 * mm, y, f"{item['art']} — {item['price']} {deal['currency']}")
            y -= 8 * mm
            if y < 20 * mm:
                c.showPage()
                y = 270 * mm

        c.save()
        return path
