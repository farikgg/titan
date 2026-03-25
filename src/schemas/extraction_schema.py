from pydantic import BaseModel
from typing import List, Optional

class ExtractionItem(BaseModel):
    art: str
    name: str # Предложенное название (или из каталога)
    raw_name: Optional[str] = None # Как было в письме
    quantity: float = 1.0
    unit: Optional[str] = None # кг, л, шт и т.д.
    price: Optional[float] = None
    currency: Optional[str] = "EUR"

class ExtractionResult(BaseModel):
    items: List[ExtractionItem]
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    warranty_terms: Optional[str] = None
    notes: Optional[str] = None
    dates: List[str] = [] # В формате YYYY-MM-DD
