"""
file_processor.py — Orchestrates the full receipt processing pipeline.

Folder structure:
    root_folder/
        YYYY/              ← year folder (auto-created)
            MM-YYYY/       ← monthly folder  e.g. "03-2026"
            YYYY שנתי/     ← annual expenses
            Non-Business/  ← non-business receipts

Filename format:
    [expense_type] - [amount][currency] - [provider] - YYYY-MM-DD[.רכוש קבוע].ext
    NOT_BUSINESS - [amount][currency] - [provider] - YYYY-MM-DD.ext  (non-business)
    Possible-duplicate suffix: [ייתכן כפול]
"""

from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from datetime import date

from googleapiclient.discovery import Resource

from config import (
    ANNUAL_FOLDER_SUFFIX,
    DRIVE_FOLDER_ID,
    FIXED_ASSET_SUFFIX,
)
from deduplication import (
    compute_md5,
    is_duplicate,
    is_amount_date_duplicate,
    load_metadata,
    record_file,
    save_metadata,
)
from drive_service import find_or_create_folder, upload_file
from gemini_service import analyze_receipt

logger = logging.getLogger(__name__)

NON_BUSINESS_FOLDER = "Non-Business"

# Supported MIME types by extension
MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
}


@dataclass
class ProcessResult:
    original_filename: str
    status: str  # "success" | "duplicate" | "error" | "skipped"
    message: str = ""
    target_folder: str = ""
    new_filename: str = ""
    drive_link: str = ""
    ai_data: dict = field(default_factory=dict)
    is_business: bool = True


def _get_mime_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


def _year_folder(service: Resource, year: str, root_folder_id: str) -> str:
    """Return/create the year-level folder (e.g. '2026')."""
    return find_or_create_folder(service, year, root_folder_id)


def _build_folder_path(
    service: Resource,
    ai_data: dict,
    root_folder_id: str,
) -> tuple[str, str]:
    """
    Return (folder_id, folder_display_name) for the target leaf folder.
    Structure: root → YYYY → (MM-YYYY | YYYY שנתי) [ → NON BUSINESS ]
    """
    from config import NON_BUSINESS_FOLDER_NAME as NB_NAME
    
    raw_date = ai_data.get("date", str(date.today()))
    try:
        parsed = date.fromisoformat(raw_date)
    except ValueError:
        parsed = date.today()

    year_str = str(parsed.year)
    year_id = _year_folder(service, year_str, root_folder_id)

    is_business = ai_data.get("is_business_expense", True)

    # Base folder (Monthly or Annual)
    if ai_data.get("is_annual"):
        base_name = f"{year_str} {ANNUAL_FOLDER_SUFFIX}"
    else:
        month_str = f"{parsed.month:02d}-{parsed.year}"
        base_name = month_str

    base_id = find_or_create_folder(service, base_name, year_id)
    
    # If not business, nest it further
    if not is_business:
        target_id = find_or_create_folder(service, NB_NAME, base_id)
        display = f"{year_str}/{base_name}/{NB_NAME}"
    else:
        target_id = base_id
        display = f"{year_str}/{base_name}"

    return target_id, display


def _format_amount(ai_data: dict) -> str:
    """Return e.g. '₪299.00' or '$19.99' or '' if unknown."""
    amount = ai_data.get("total_amount")
    if amount is None:
        return ""
    currency = ai_data.get("currency", "ILS")
    symbols = {"ILS": "₪", "USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency, currency)
    return f"{symbol}{amount:,.2f}"


def _build_filename(ai_data: dict, original_filename: str, possibly_duplicate: bool = False) -> str:
    """
    Build the target filename.
    Business:     [type] - [amount][currency] - [provider] - YYYY-MM-DD[.רכוש קבוע].ext
    Non-business: NOT_BUSINESS - [amount][currency] - [provider] - YYYY-MM-DD.ext
    """
    ext = os.path.splitext(original_filename)[1].lower() or ".pdf"
    date_str = ai_data.get("date", str(date.today()))
    provider = ai_data.get("provider", "ספק לא ידוע").strip()
    expense = ai_data.get("expense_type", "הוצאה").strip()
    is_business = ai_data.get("is_business_expense", True)
    amount_str = _format_amount(ai_data)

    # Sanitise characters invalid in filenames
    for ch in r'\/:*?"<>|':
        provider = provider.replace(ch, "")
        expense = expense.replace(ch, "")

    if not is_business:
        expense = "NOT_BUSINESS"

    parts = [expense]
    if amount_str:
        parts.append(amount_str)
    parts.append(provider)
    parts.append(date_str)

    name = " - ".join(parts)

    if is_business and ai_data.get("is_fixed_asset"):
        name = f"{name} - {FIXED_ASSET_SUFFIX}"

    if possibly_duplicate:
        name = f"{name} [ייתכן כפול]"

    return f"{name}{ext}"


def process_file(
    file_bytes: bytes,
    original_filename: str,
    service: Resource,
    root_folder_id: str = DRIVE_FOLDER_ID,
    email_date: Optional[str] = None,
) -> ProcessResult:
    """Full pipeline for a single uploaded receipt file."""

    # 1. MD5 deduplication (hard dedupe)
    md5_hash = compute_md5(file_bytes)
    metadata, metadata_file_id = load_metadata(service, root_folder_id)

    if is_duplicate(md5_hash, metadata):
        logger.info("Duplicate detected for '%s'", original_filename)
        return ProcessResult(
            original_filename=original_filename,
            status="duplicate",
            message=f"הקובץ '{original_filename}' כבר הועלה בעבר (MD5 זהה).",
        )

    # 2. Gemini AI classification
    mime_type = _get_mime_type(original_filename)
    try:
        ai_data = analyze_receipt(file_bytes, mime_type, email_date=email_date)
    except Exception as exc:
        logger.error("Gemini error for '%s': %s", original_filename, exc)
        return ProcessResult(
            original_filename=original_filename,
            status="error",
            message=f"שגיאה בניתוח AI: {exc}",
        )

    # 2.5 Strict Document check
    if not ai_data.get("is_actual_financial_document", True):
        logger.info("Skipping '%s': identified by AI as non-financial document.", original_filename)
        return ProcessResult(
            original_filename=original_filename,
            status="skipped",
            message="הקובץ זוהה כמידע כללי או הזמנה לאירוע (לא חשבונית/קבלה)",
            ai_data=ai_data,
        )

    # 3. Secondary dedupe: same date + same amount
    possibly_duplicate = is_amount_date_duplicate(
        ai_data.get("date", ""),
        ai_data.get("total_amount"),
        metadata,
    )

    # 4. Determine target folder path (root → year → month/annual/non-business)
    try:
        target_folder_id, folder_display = _build_folder_path(service, ai_data, root_folder_id)
    except Exception as exc:
        logger.error("Drive folder error: %s", exc)
        return ProcessResult(
            original_filename=original_filename,
            status="error",
            message=f"שגיאה ביצירת תיקייה ב-Drive: {exc}",
            ai_data=ai_data,
        )

    # 5. Build filename and upload
    new_filename = _build_filename(ai_data, original_filename, possibly_duplicate)
    try:
        _, drive_link = upload_file(service, file_bytes, new_filename, mime_type, target_folder_id)
    except Exception as exc:
        err = str(exc)
        if "storageQuotaExceeded" in err:
            msg = (
                "❌ שגיאת Drive: Service Account אינו יכול להעלות ל-My Drive.\n"
                "פתרון: השתמש ב-OAuth2 (הרץ setup_auth.py) או Shared Drive."
            )
        else:
            msg = f"שגיאת העלאה ל-Drive: {exc}"
        logger.error("Upload error for '%s': %s", original_filename, exc)
        return ProcessResult(
            original_filename=original_filename, status="error",
            message=msg, target_folder=folder_display,
            new_filename=new_filename, ai_data=ai_data,
        )

    # 6. Update metadata.json
    updated_metadata = record_file(md5_hash, original_filename, drive_link, metadata, ai_data)
    try:
        save_metadata(service, root_folder_id, updated_metadata, metadata_file_id)
    except Exception as exc:
        logger.warning("Could not save metadata: %s", exc)

    is_biz = ai_data.get("is_business_expense", True)
    return ProcessResult(
        original_filename=original_filename,
        status="success",
        message=f"הועלה לתיקייה '{folder_display}'",
        target_folder=folder_display,
        new_filename=new_filename,
        drive_link=drive_link,
        ai_data=ai_data,
        is_business=is_biz,
    )
