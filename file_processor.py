"""
file_processor.py — Orchestrates the full receipt processing pipeline.

Flow: MD5 check → Gemini AI → Build filename → Ensure folder → Upload → Update metadata
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
    HEBREW_MONTHS,
)
from deduplication import (
    compute_md5,
    is_duplicate,
    load_metadata,
    record_file,
    save_metadata,
)
from drive_service import find_or_create_folder, upload_file
from gemini_service import analyze_receipt

logger = logging.getLogger(__name__)

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
    status: str  # "success" | "duplicate" | "error"
    message: str = ""
    target_folder: str = ""
    new_filename: str = ""
    drive_link: str = ""
    ai_data: dict = field(default_factory=dict)


def _get_mime_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


def _build_folder_name(ai_data: dict) -> str:
    """Return the Drive folder name based on AI classification."""
    if ai_data.get("is_annual"):
        year = ai_data["date"][:4]
        return f"{year} {ANNUAL_FOLDER_SUFFIX}"

    try:
        parsed_date = date.fromisoformat(ai_data["date"])
        month_name = HEBREW_MONTHS[parsed_date.month]
        return f"{month_name} {parsed_date.year}"
    except (ValueError, KeyError):
        today = date.today()
        return f"{HEBREW_MONTHS[today.month]} {today.year}"


def _build_filename(ai_data: dict, original_filename: str) -> str:
    """
    Build the target filename:
        YYYY-MM-DD - Provider - ExpenseType[.רכוש קבוע].ext
    """
    ext = os.path.splitext(original_filename)[1].lower()
    date_str = ai_data.get("date", str(date.today()))
    provider = ai_data.get("provider", "ספק לא ידוע").strip()
    expense = ai_data.get("expense_type", "הוצאה").strip()

    # Sanitise characters that are invalid in file names
    for ch in r'\/:*?"<>|':
        provider = provider.replace(ch, "")
        expense = expense.replace(ch, "")

    name = f"{expense} - {provider} - {date_str}"

    if ai_data.get("is_fixed_asset"):
        name = f"{name} - {FIXED_ASSET_SUFFIX}"

    return f"{name}{ext}"


def process_file(
    file_bytes: bytes,
    original_filename: str,
    service: Resource,
    root_folder_id: str = DRIVE_FOLDER_ID,
) -> ProcessResult:
    """
    Full pipeline for a single uploaded receipt file.

    Returns a ProcessResult describing the outcome.
    """
    # 1. MD5 deduplication
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
        ai_data = analyze_receipt(file_bytes, mime_type)
    except Exception as exc:
        logger.error("Gemini error for '%s': %s", original_filename, exc)
        return ProcessResult(
            original_filename=original_filename,
            status="error",
            message=f"שגיאה בניתוח AI: {exc}",
        )

    # 3. Determine target folder
    folder_name = _build_folder_name(ai_data)
    try:
        target_folder_id = find_or_create_folder(service, folder_name, root_folder_id)
    except Exception as exc:
        logger.error("Drive folder error: %s", exc)
        return ProcessResult(
            original_filename=original_filename,
            status="error",
            message=f"שגיאה ביצירת תיקייה ב-Drive: {exc}",
            ai_data=ai_data,
        )

    # 4. Build filename and upload
    new_filename = _build_filename(ai_data, original_filename)
    try:
        _, drive_link = upload_file(
            service, file_bytes, new_filename, mime_type, target_folder_id
        )
    except Exception as exc:
        error_str = str(exc)
        if "storageQuotaExceeded" in error_str:
            msg = (
                "❌ שגיאת Drive: ה-Service Account אינו יכול להעלות לתיקיית 'My Drive' רגילה.\n\n"
                "**פתרון — צור Shared Drive:**\n"
                "1. כנס ל- drive.google.com\n"
                "2. לחץ 'Shared drives' בצד שמאל → 'New'\n"
                "3. צור Shared Drive חדש (למשל: 'חשבוניות עסק')\n"
                "4. לחץ על הגדרות ← 'Manage members'\n"
                f"5. הוסף את כתובת ה-Service Account שלך כ-'Content manager'\n"
                "6. צור תיקייה בתוך ה-Shared Drive והעתק את המזהה שלה מה-URL\n"
                "7. עדכן DRIVE_FOLDER_ID בקובץ .env בתיקיית הפרויקט"
            )
        else:
            msg = f"שגיאת העלאה ל-Drive: {exc}"
        logger.error("Drive upload error for '%s': %s", original_filename, exc)
        return ProcessResult(
            original_filename=original_filename,
            status="error",
            message=msg,
            target_folder=folder_name,
            new_filename=new_filename,
            ai_data=ai_data,
        )


    # 5. Update metadata.json
    updated_metadata = record_file(md5_hash, original_filename, drive_link, metadata)
    try:
        save_metadata(service, root_folder_id, updated_metadata, metadata_file_id)
    except Exception as exc:
        logger.warning("Could not save metadata: %s", exc)

    return ProcessResult(
        original_filename=original_filename,
        status="success",
        message=f"הקובץ הועלה בהצלחה לתיקייה '{folder_name}'",
        target_folder=folder_name,
        new_filename=new_filename,
        drive_link=drive_link,
        ai_data=ai_data,
    )
