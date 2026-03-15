"""
gmail_scanner.py — Orchestrates scanning Gmail inbox for receipts.

Flow:
  1. Load processed message IDs from metadata.json
  2. Query Gmail → filter already-processed
  3. For each new email: extract receipt → Gemini AI → upload to Drive
  4. Mark all scanned IDs as processed (even non-receipts, to skip next time)
  5. Save updated metadata
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Callable

from googleapiclient.discovery import Resource

from config import DRIVE_FOLDER_ID
from deduplication import (
    get_processed_email_ids,
    load_metadata,
    mark_emails_processed,
    save_metadata,
)
from email_processor import extract_receipt, is_likely_receipt
from file_processor import ProcessResult, process_file
from gmail_service import EmailMessage, fetch_email, list_receipt_message_ids

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    msg_id: str
    subject: str
    sender: str
    process_result: ProcessResult | None = None
    skipped: bool = False   # True = no receipt found in email
    skip_reason: str = ""   # e.g. "low_score", "zero_amount", "exclusion_list"
    error: str = ""


def scan_gmail_for_receipts(
    drive_service: Resource,
    gmail_service: Resource,
    root_folder_id: str = DRIVE_FOLDER_ID,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> list[ScanResult]:
    """
    Scan Gmail inbox, find receipt emails not yet processed, and upload to Drive.

    Args:
        drive_service: authenticated Drive API resource
        gmail_service: authenticated Gmail API resource
        root_folder_id: root Drive folder ID
        progress_cb: optional callback(current, total, status_text)

    Returns:
        list of ScanResult objects
    """
    # 1. Load metadata → get already-processed email IDs
    metadata, metadata_file_id = load_metadata(drive_service, root_folder_id)
    processed_ids = get_processed_email_ids(metadata)
    logger.info("Already processed %d email IDs.", len(processed_ids))

    # 2. Query Gmail for new candidate emails
    new_msg_ids = list_receipt_message_ids(gmail_service, exclude_ids=processed_ids)
    total = len(new_msg_ids)
    logger.info("New emails to check: %d", total)

    if total == 0:
        return []

    results: list[ScanResult] = []
    newly_scanned_ids: list[str] = []

    def _save_checkpoint():
        """Helper to persist current progress to Drive."""
        nonlocal newly_scanned_ids
        if not newly_scanned_ids:
            return
        meta, file_id = load_metadata(drive_service, root_folder_id)
        updated = mark_emails_processed(newly_scanned_ids, meta)
        try:
            save_metadata(drive_service, root_folder_id, updated, file_id)
            logger.info("Checkpoint: Saved %d processed IDs.", len(newly_scanned_ids))
            newly_scanned_ids = []  # Clear after saving
        except Exception as exc:
            logger.warning("Checkpoint save failed: %s", exc)

    total_checked = 0
    for idx, msg_id in enumerate(new_msg_ids):
        total_checked += 1
        if progress_cb:
            progress_cb(idx, total, f"בודק מיילים... ({idx + 1}/{total})")

        # 3. Fetch full email
        try:
            email: EmailMessage = fetch_email(gmail_service, msg_id)
        except Exception as exc:
            logger.error("Failed to fetch email %s: %s", msg_id, exc)
            newly_scanned_ids.append(msg_id)
            results.append(ScanResult(
                msg_id=msg_id, subject="(שגיאה בטעינה)", sender="",
                error=str(exc),
            ))
            continue

        # 4. Check likelihood (fast filter)
        likely, reason = is_likely_receipt(email)
        if not likely:
            # We mark as seen but don't spam the UI callback for every skip
            newly_scanned_ids.append(msg_id)
            results.append(ScanResult(
                msg_id=msg_id, subject=email.subject,
                sender=email.sender, skipped=True,
                skip_reason=reason
            ))
            # Save checkpoint every 10 skips to avoid huge redos
            if len(newly_scanned_ids) >= 10:
                _save_checkpoint()
            continue

        # 5. Extract receipt content
        receipt = extract_receipt(email)
        newly_scanned_ids.append(msg_id) 

        if receipt is None:
            logger.info("No receipt found in email: %s", email.subject)
            results.append(ScanResult(
                msg_id=msg_id, subject=email.subject,
                sender=email.sender, skipped=True,
            ))
            continue

        # 5. Process through standard pipeline
        if progress_cb:
            progress_cb(idx, total, f"**נמצאה קבלה!** מעבד: {email.subject[:40]}...")

        hint_filename = receipt.filename_hint or f"{email.subject[:50]}.pdf"
        # Ensure extension matches mime type
        if receipt.mime_type == "application/pdf" and not hint_filename.endswith(".pdf"):
            hint_filename = hint_filename.rsplit(".", 1)[0] + ".pdf"

        proc_result = process_file(
            file_bytes=receipt.data,
            original_filename=hint_filename,
            service=drive_service,
            root_folder_id=root_folder_id,
            email_date=email.date,
        )

        results.append(ScanResult(
            msg_id=msg_id,
            subject=email.subject,
            sender=email.sender,
            process_result=proc_result,
        ))

        # Always save checkpoint after a successful upload processing
        _save_checkpoint()

    # 6. Final save for any remaining IDs
    _save_checkpoint()

    if progress_cb:
        progress_cb(total, total, "✅ סריקת מייל הושלמה!")

    return results
