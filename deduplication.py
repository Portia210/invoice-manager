"""
deduplication.py — MD5 hashing and metadata.json management in Google Drive.

metadata.json structure:
{
  "hashes": {
    "<md5>": {"original_filename": "...", "drive_link": "...", "date": "...", "amount": 123.0}
  },
  "processed_email_ids": ["<gmail_msg_id>", ...]
}
"""

from __future__ import annotations
import hashlib
import io
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource

from config import METADATA_FILENAME

logger = logging.getLogger(__name__)


def compute_md5(file_bytes: bytes) -> str:
    """Return the hex MD5 digest of the given bytes."""
    return hashlib.md5(file_bytes).hexdigest()


def _find_metadata_file(service: "Resource", folder_id: str) -> str | None:
    """Return the Drive file ID of metadata.json in the given folder, or None."""
    query = (
        f"name='{METADATA_FILENAME}' "
        f"and '{folder_id}' in parents "
        f"and trashed=false"
    )
    result = (
        service.files()
        .list(
            q=query,
            fields="files(id)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    if len(files) > 1:
        logger.warning("Found %d metadata.json files! Using the first one (id=%s)", len(files), files[0]["id"])
    return files[0]["id"] if files else None


def load_metadata(service: "Resource", folder_id: str) -> tuple[dict, str | None]:
    """
    Load metadata.json from Google Drive.
    Returns: (metadata_dict, file_id_or_None)
    """
    file_id = _find_metadata_file(service, folder_id)
    if file_id is None:
        return {}, None

    content = (
        service.files()
        .get_media(fileId=file_id, supportsAllDrives=True)
        .execute()
    )
    try:
        return json.loads(content), file_id
    except json.JSONDecodeError:
        logger.warning("metadata.json is corrupt — starting fresh.")
        return {}, file_id


def save_metadata(
    service: "Resource",
    folder_id: str,
    metadata: dict,
    existing_file_id: str | None,
) -> str:
    """Create or update metadata.json in the given Google Drive folder."""
    from googleapiclient.http import MediaIoBaseUpload

    content_bytes = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype="application/json")

    if existing_file_id:
        (
            service.files()
            .update(fileId=existing_file_id, media_body=media, supportsAllDrives=True)
            .execute()
        )
        logger.debug("Updated metadata.json (id=%s)", existing_file_id)
        return existing_file_id
    else:
        file_metadata = {"name": METADATA_FILENAME, "parents": [folder_id]}
        folder = (
            service.files()
            .create(body=file_metadata, media_body=media, supportsAllDrives=True)
            .execute()
        )
        new_id = folder["id"]
        logger.debug("Created metadata.json in folder %s (id=%s)", folder_id, new_id)
        return new_id


def is_duplicate(md5_hash: str, metadata: dict) -> bool:
    """Return True if this hash already exists in the metadata store."""
    return md5_hash in metadata.get("hashes", {})


def is_amount_date_duplicate(
    date_str: str,
    amount: float | None,
    metadata: dict,
) -> bool:
    """
    Secondary dedup check: return True if another file with the same date
    AND same amount already exists in metadata.
    """
    if not date_str or amount is None:
        return False
    for entry in metadata.get("hashes", {}).values():
        if entry.get("date") == date_str and entry.get("amount") == amount:
            return True
    return False


def record_file(
    md5_hash: str,
    filename: str,
    drive_link: str,
    metadata: dict,
    ai_data: dict | None = None,
) -> dict:
    """Add a processed file record to the metadata dict and return it."""
    if "hashes" not in metadata:
        metadata["hashes"] = {}
    entry: dict = {"original_filename": filename, "drive_link": drive_link}
    if ai_data:
        entry["date"] = ai_data.get("date", "")
        entry["amount"] = ai_data.get("total_amount")
        entry["provider"] = ai_data.get("provider", "")
        entry["expense_type"] = ai_data.get("expense_type", "")
        entry["is_business"] = ai_data.get("is_business_expense", True)
    metadata["hashes"][md5_hash] = entry
    return metadata


# ── Gmail processed IDs ────────────────────────────────────────────────────────

def get_processed_email_ids(metadata: dict) -> set[str]:
    """Return the set of Gmail message IDs already processed."""
    return set(metadata.get("processed_email_ids", []))


def mark_emails_processed(msg_ids: list[str], metadata: dict) -> dict:
    """Add message IDs to the processed set in metadata."""
    existing = set(metadata.get("processed_email_ids", []))
    existing.update(msg_ids)
    metadata["processed_email_ids"] = sorted(existing)
    return metadata
