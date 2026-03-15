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


import concurrent.futures
import threading

def scan_gmail_for_receipts(
    drive_service: Resource,
    gmail_service: Resource,
    root_folder_id: str = DRIVE_FOLDER_ID,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> list[ScanResult]:
    """
    Scan Gmail inbox, find receipt emails not yet processed, and upload to Drive.
    Uses concurrency to speed up processing.
    """
    # 1. Load metadata → get already-processed email IDs
    metadata, metadata_file_id = load_metadata(drive_service, root_folder_id)
    processed_ids = get_processed_email_ids(metadata)
    logger.debug("Already processed %d email IDs.", len(processed_ids))

    # 2. Query Gmail for new candidate emails
    new_msg_ids = list_receipt_message_ids(gmail_service, exclude_ids=processed_ids)
    total = len(new_msg_ids)
    logger.debug("New emails to check: %d", total)

    if total == 0:
        return []

    results: list[ScanResult] = []
    newly_scanned_ids: list[str] = []
    
    metadata_lock = threading.Lock()
    results_lock = threading.Lock()
    
    def _save_checkpoint():
        """Helper to persist current progress to Drive."""
        with metadata_lock:
            if not newly_scanned_ids:
                return
            
            # Record current IDs in metadata
            mark_emails_processed(newly_scanned_ids, metadata)
            
            try:
                save_metadata(drive_service, root_folder_id, metadata, metadata_file_id)
                logger.debug("Checkpoint: Saved %d processed IDs.", len(newly_scanned_ids))
                newly_scanned_ids.clear()
            except Exception as exc:
                logger.warning("Checkpoint save failed: %s", exc)

    def _worker(msg_id: str, idx: int) -> ScanResult:
        """Process a single email in a thread."""
        try:
            # Update progress (UI is thread-safe for basic text updates in Streamlit)
            if progress_cb and idx % 2 == 0: # Reduce callback frequency
                progress_cb(idx, total, f"בודק מיילים... ({idx + 1}/{total})")

            # 3. Fetch full email
            email: EmailMessage = fetch_email(gmail_service, msg_id)
            
            # 4. Check likelihood (fast filter)
            likely, reason = is_likely_receipt(email)
            if not likely:
                with metadata_lock:
                    newly_scanned_ids.append(msg_id)
                return ScanResult(
                    msg_id=msg_id, subject=email.subject,
                    sender=email.sender, skipped=True,
                    skip_reason=reason
                )

            # 5. Extract receipt content
            receipt = extract_receipt(email)
            if receipt is None:
                with metadata_lock:
                    newly_scanned_ids.append(msg_id)
                return ScanResult(
                    msg_id=msg_id, subject=email.subject,
                    sender=email.sender, skipped=True,
                    skip_reason="לא נמצא תוכן קבלה במייל"
                )

            # 6. Process through standard pipeline
            if progress_cb:
                progress_cb(idx, total, f"**קבלת {email.provider or 'X'}!** מעבד: {email.subject[:30]}...")

            hint_filename = receipt.filename_hint or f"{email.subject[:50]}.pdf"
            if receipt.mime_type == "application/pdf" and not hint_filename.endswith(".pdf"):
                hint_filename = hint_filename.rsplit(".", 1)[0] + ".pdf"

            # Pass shared metadata and LOCK it during record_file (inside process_file)
            # Actually, process_file now doesn't save metadata, it just updates the dict.
            # We must lock the dict update.
            
            # We call everything EXCEPT recording metadata outside the lock
            # We pass a CLONE of metadata for dedupe or trust the MD5 which is unique
            
            proc_result = process_file(
                file_bytes=receipt.data,
                original_filename=hint_filename,
                service=drive_service,
                root_folder_id=root_folder_id,
                email_date=email.date,
                metadata=metadata, # Dedupe check uses shared dict
                metadata_file_id=None, # Don't save inside!
            )

            # Update shared structures under lock
            with metadata_lock:
                newly_scanned_ids.append(msg_id)
                # Note: record_file was already called inside process_file on the shared 'metadata' dict
            
            return ScanResult(
                msg_id=msg_id,
                subject=email.subject,
                sender=email.sender,
                process_result=proc_result,
            )

        except Exception as exc:
            logger.error("Worker error for %s: %s", msg_id, exc)
            with metadata_lock:
                newly_scanned_ids.append(msg_id)
            return ScanResult(msg_id=msg_id, subject="(שגיאה)", sender="", error=str(exc))

    # Run with ThreadPoolExecutor
    max_workers = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_worker, mid, i) for i, mid in enumerate(new_msg_ids)]
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            res = future.result()
            with results_lock:
                results.append(res)
            
            # Periodic checkpoint every 10 items
            if i % 10 == 0:
                _save_checkpoint()

    # Final save
    _save_checkpoint()

    if progress_cb:
        progress_cb(total, total, "✅ סריקת מייל הושלמה!")

    return results
