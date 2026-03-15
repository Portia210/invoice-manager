"""
gemini_service.py — AI receipt analysis using Gemini Flash (temperature=0).
Structured output is enforced via a Pydantic schema passed to response_schema,
guaranteeing Gemini always returns a valid, typed JSON object.
"""
from __future__ import annotations
import logger_setup

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
    thinking_process: str = Field(
        description="ניתוח לוגי צעד-אחר-צעד: האם זה מסמך פיננסי סופי? האם גוף המייל תומך בזה? האם יש ח.פ. ומספר מסמך?"
    )
    is_actual_financial_document: bool = Field(
        description="True רק אם זה מסמך סופי המעיד על עסקה שבוצעה (חשבונית מס/קבלה). False עבור הצעות מחיר, חומרי לימוד, או הרשמות."
    )
    date: str = Field(
        description="תאריך הקבלה בפורמט YYYY-MM-DD. אם מדובר בתמונה (וואטסאפ), חפש היטב את תאריך הצילום או התאריך המופיע במסמך."
    )
    provider: str = Field(description="שם הספק / העסק. אם בתמונה, נסה לזהות לוגו או כותרת.")
    expense_type: str = Field(
        description=f"סוג ההוצאה. עדיפות גבוהה לבחירה מהרשימה הבאה, אך אם מדובר בהוצאה עסקית ברורה שאינה מופיעה, ציין שם קצר וקולע בעברית. רשימה: {ALL_EXPENSES}"
    )
    is_annual: bool = Field(
        default=False,
        description=f"True רק עבור הוצאות שנתיות (למשל ביטוחים, אגרות רכב). רשימה לעזר: {ANNUAL_EXPENSES}",
    )
    is_fixed_asset: bool = Field(
        default=False,
        description=f"True רק עבור רכוש קבוע (קניית רכב, מחשב, טלפון). רשימה לעזר: {FIXED_ASSETS}",
    )
    is_business_expense: bool = Field(
        default=True,
        description="True אם זו הוצאה עסקית מוכרת (כולל ספק סביר). False עבור קניות פרטיות מובהקות.",
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
1. **גמישות בקטגוריות**: עדיף לבחור קטגוריה מרשימת ה-ALL_EXPENSES. אם ההוצאה היא עסקית מובהקת אך אינה ברשימה (למשל 'טלפון' או 'ציוד היקפי'), ציין שם קטגוריה תיאורי וקצר בעברית.
2. is_business_expense=false עבור: קניות פרטיות מובהקות, בידור אישי, מנויים אישיים (נטפליקס, ספוטיפיי), מתנות פרטיות.
3. תאריך בפורמט YYYY-MM-DD. אם לא ידוע — השתמש בתאריך היום ({date.today()}).
4. is_annual=true עבור פריטים שנתיים (ביטוחים, אגרות).
5. is_fixed_asset=true עבור רכישת נכסים (מחשב חדש, רכב, מסך).

רשימת הוצאות מוכרות:
{json.dumps(ALL_EXPENSES, ensure_ascii=False)}

הוצאות שנתיות (is_annual=true):
{json.dumps(ANNUAL_EXPENSES, ensure_ascii=False)}

רכוש קבוע (is_fixed_asset=true):
{json.dumps(FIXED_ASSETS, ensure_ascii=False)}
"""


def analyze_receipt(file_bytes: bytes, mime_type: str, email_date: Optional[str] = None, email_body: Optional[str] = None) -> dict:
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
    
    if email_body:
        # Keep body context concise but useful
        prompt += f"\n\n**הקשר מגוף המייל:**\n{email_body[:2000]}\n"

    prompt += """
**כללי סינון מחמירים (is_actual_financial_document):**
1. **ניתוח לוגי (thinking_process):** לפני מילוי השדות, בצע ניתוח פנימי: 
   - האם המייל/מסמך הוא רק "ברוך הבא" או "חומרי לימוד"? (אם כן -> False).
   - האם המייל הוא "הצעת מחיר" (Quote/Offer) ולא אישור תשלום סופי? (אם כן -> False).
   - האם יש בעל עסק, מספר עוסק (ח.פ./ע.מ.), מספר מסמך ייחודי וסכום סופי לתשלום?
2. **החזר `false` עבור:**
    - הצעות מחיר, הזמנות לאירועים, תעודות משלוח, ניוזלטרים.
    - **חומרי לימוד ותוכן אקדמי**: סיכומי שיעור, דפי הנחיות, סילבוס (גם אם יש מחיר קורס במייל).
    - **הודעות מערכת**: "הצטרפת בהצלחה", "פרטי ההתחברות שלך", "ברוך הבא לקורס".
3. **החזר `true` רק עבור:** חשבונית מס, קבלה, חשבונית עסקה ששולמה, או אישור תשלום סופי מחנות/ספק.

**דגשי סיווג וכללים:**
- **תוכנה ודיגיטל:** מנויים לכל סוגי התוכנה והשירותים הדיגיטליים (SaaS, Cloud, YouTube Music, Google) הם **תמיד** הוצאה עסקית.
- **במקרה של ספק:** אם המסמך נראה פיננסי אך לא ברור אם הוא למטרה עסקית, **ברירת המחדל היא עסקית (True)**.
- **אוכל וארוחות (Meals):** ארוחות אינן הוצאה עסקית (False). כיבוד קל (קפה/עוגיות למשרד) הוא כן (True).
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
