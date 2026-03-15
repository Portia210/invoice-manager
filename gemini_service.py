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
# ── Pydantic schema — Gemini will be forced to match this exactly ───────────────
class ReceiptAnalysis(BaseModel):
    is_actual_financial_document: bool = Field(
        description="True only if this is a real receipt, invoice, or payment confirmation with a price/transaction. False for invitations, marketing, tickets without price, or general info."
    )
    date: str = Field(
        description="תאריך הקבלה בפורמט YYYY-MM-DD. אם מדובר בתמונה (וואטסאפ), חפש היטב את תאריך הצילום או התאריך המופיע במסמך."
    )
    provider: str = Field(description="שם הספק / העסק. אם בתמונה, נסה לזהות לוגו או כותרת.")
    expense_type: str = Field(
        description=f"סוג ההוצאה מהרשימה בלבד. אם לא הוצאה עסקית, החזר 'NOT_BUSINESS'. רשימה: {ALL_EXPENSES}"
    )
    is_annual: bool = Field(
        default=False,
        description=f"True רק עבור הוצאות שנתיות: {ANNUAL_EXPENSES}",
    )
    is_fixed_asset: bool = Field(
        default=False,
        description=f"True רק עבור רכוש קבוע: {FIXED_ASSETS}",
    )
    is_business_expense: bool = Field(
        default=True,
        description="True אם זו הוצאה עסקית מוכרת. False עבור קניות פרטיות, מנויים אישיים, בידור וכד'.",
    )
    confidence: float = Field(
        default=1.0,
        description="רמת הביטחון בסיווג, בין 0.0 ל-1.0",
    )
    total_amount: Optional[float] = Field(
        default=None, description='סכום כולל (מספר בלבד, ללא סימן מטבע)'
    )
    currency: str = Field(default="ILS", description='מטבע: ILS, USD, EUR וכד\'')


_PROMPT = f"""
אתה מנתח קבלות וחשבוניות עסקיות בישראל.
נתח את הקובץ המצורף (תמונה או PDF) ומלא את כל שדות ה-JSON בדיוק רב.

**דגש על איכות הזיהוי:**
- אם זו תמונה (מצלמה, WhatsApp), נסה לפענח טקסט מטושטש כדי למצוא תאריך, ספק וסכום. 
- אל תוותר מהר על שדות; חפש לוגואים, כותרות או חתימות.

**כללי סינון (is_actual_financial_document):**
- החזר `true` רק עבור מסמכים המעידים על עסקה כספית: קבלה, חשבונית מס, אישור תשלום, Receipt.
- החזר `false` עבור: הזמנות לאירועים (Invitations), כרטיסי כניסה ללא מחיר, פרסומות, הצעות מחיר, או מיילים אינפורמטיביים.

**כללי סיווג:**
1. expense_type חייב להיות מהרשימה, או 'NOT_BUSINESS' אם לא הוצאה עסקית.
2. is_business_expense=false עבור: קניות פרטיות, בידור, מנויים אישיים (נטפליקס, ספוטיפיי וכד'), מתנות.
3. תאריך בפורמט YYYY-MM-DD. אם לא ידוע — השתמש בתאריך היום ({date.today()}).
4. is_annual=true **רק** עבור פריטים מרשימת ההוצאות השנתיות.
5. is_fixed_asset=true **רק** עבור רכוש קבוע.

רשימת הוצאות מוכרות:
{json.dumps(ALL_EXPENSES, ensure_ascii=False)}

הוצאות שנתיות (is_annual=true):
{json.dumps(ANNUAL_EXPENSES, ensure_ascii=False)}

רכוש קבוע (is_fixed_asset=true):
{json.dumps(FIXED_ASSETS, ensure_ascii=False)}
"""


def analyze_receipt(file_bytes: bytes, mime_type: str, email_date: Optional[str] = None) -> dict:
    """
    Send the receipt image/PDF to Gemini and return the parsed result as a dict.
    Uses response_schema=ReceiptAnalysis to enforce structured output.
    
    Args:
        file_bytes: The raw file data.
        mime_type: MIME type (image/jpeg, application/pdf, etc).
        email_date: Optional context of when the email was received.
    """
    blob = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

    prompt = _PROMPT
    if email_date:
        prompt += f"\n**הערה חשובה:** המייל התקבל בתאריך {email_date}. יש סבירות גבוהה שהתאריך במסמך זהה או סמוך לתאריך זה. השתמש בזה כעזר לזיהוי."

    # Specific strictness for shops and professionals
    prompt += """
**דגשי סיווג נוספים:**
- **תוכנות ודיגיטל (SaaS, Subscriptions):** מנויים לתוכנות, שירותי ענן, וכלי עבודה דיגיטליים הם **תמיד** הוצאה עסקית (is_business_expense=true).
- **במקרה של ספק:** אם לא ברור לחלוטין אם ההוצאה עסקית או פרטית, **ברירת המחדל היא הוצאה עסקית** (is_business_expense=true).
- **קניות ואוכל (TEMU, Amazon, Wolt, 10bis):** סווג כהוצאה **פרטית** (is_business_expense=false) אלא אם ברור לחלוטין שמדובר ברכישה עסקית למופת (למשל חלקי מחשב בלבד).
- **אנשי מקצוע:** זהה שמות כמו "רו"ח", "רואה חשבון", "ייעוץ מס" כהוצאה עסקית בביטחון גבוה.
- **סינון נוקשה (is_actual_financial_document):** שלול מסמכים שאינם אישורי תשלום סופיים (הכרזות, הזמנות לאירועים, הצעות מחיר).
"""

    response = _client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, blob],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=ReceiptAnalysis,
        ),
    )
    # Log results at debug level only
    logger.debug("Gemini result: %s", response.text)

    try:
        result = ReceiptAnalysis.model_validate_json(response.text)
    except Exception as exc:
        logger.error("Schema validation failed: %s\nRaw: %s", exc, response.text)
        raise ValueError(f"תשובת Gemini לא תואמת את הסכמה: {exc}") from exc

    logger.debug("Gemini classified: %s", result) # Downgraded from info to debug
    return result.model_dump()
