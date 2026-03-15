"""
gemini_service.py — AI receipt analysis using Gemini Flash (temperature=0).
Structured output is enforced via a Pydantic schema passed to response_schema,
guaranteeing Gemini always returns a valid, typed JSON object.
"""

from __future__ import annotations
import json
import logging
from datetime import date
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from config import (
    ALL_EXPENSES,
    ANNUAL_EXPENSES,
    FIXED_ASSETS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
)

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)


# ── Pydantic schema — Gemini will be forced to match this exactly ───────────────
class ReceiptAnalysis(BaseModel):
    date: str = Field(
        description="תאריך הקבלה בפורמט YYYY-MM-DD. אם לא ידוע, השתמש בתאריך היום."
    )
    provider: str = Field(description="שם הספק / העסק")
    expense_type: str = Field(
        description=f"סוג ההוצאה מהרשימה בלבד: {ALL_EXPENSES}"
    )
    is_annual: bool = Field(
        default=False,
        description=f"True רק עבור הוצאות שנתיות: {ANNUAL_EXPENSES}",
    )
    is_fixed_asset: bool = Field(
        default=False,
        description=f"True רק עבור רכוש קבוע: {FIXED_ASSETS}",
    )
    total_amount: Optional[float] = Field(
        default=None, description="סכום כולל בש\"ח (מספר בלבד)"
    )
    currency: str = Field(default="ILS", description="מטבע, בד\"כ ILS")


_PROMPT = f"""
אתה מנתח קבלות וחשבוניות עסקיות בישראל.
נתח את הקובץ המצורף ומלא את כל שדות ה-JSON לפי הפירוט הבא.

רשימת הוצאות מוכרות (חובה לבחור מהרשימה):
{json.dumps(ALL_EXPENSES, ensure_ascii=False)}

הוצאות שנתיות (is_annual=true):
{json.dumps(ANNUAL_EXPENSES, ensure_ascii=False)}

רכוש קבוע (is_fixed_asset=true):
{json.dumps(FIXED_ASSETS, ensure_ascii=False)}

כללים:
1. expense_type חייב להיות מהרשימה בלבד.
2. תאריך בפורמט YYYY-MM-DD. אם לא ניתן לזהות — השתמש בתאריך היום ({date.today()}).
3. is_annual=true **רק** עבור פריטים מרשימת ההוצאות השנתיות.
4. is_fixed_asset=true **רק** עבור רכוש קבוע.
"""


def analyze_receipt(file_bytes: bytes, mime_type: str) -> dict:
    """
    Send the receipt image/PDF to Gemini and return the parsed result as a dict.

    Uses response_schema=ReceiptAnalysis to enforce structured output —
    Gemini is constrained to return a valid JSON object matching the schema.
    """
    blob = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

    response = _client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[_PROMPT, blob],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=ReceiptAnalysis,
        ),
    )

    # With response_schema set, Gemini guarantees a valid object —
    # parse directly into the Pydantic model for full validation.
    try:
        result = ReceiptAnalysis.model_validate_json(response.text)
    except Exception as exc:
        logger.error("Schema validation failed: %s\nRaw: %s", exc, response.text)
        raise ValueError(f"תשובת Gemini לא תואמת את הסכמה: {exc}") from exc

    logger.info("Gemini classified: %s", result)
    return result.model_dump()
