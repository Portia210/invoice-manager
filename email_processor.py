"""
email_processor.py — Extract receipt content from emails.

Priority order for extracting the receipt:
  1. PDF attachment  → use directly
  2. Image attachment (jpg/png) → use directly (Gemini handles images)
  3. HTML body → render to PDF via Playwright (fallback: WeasyPrint)
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass

from gmail_service import EmailMessage, EmailAttachment

logger = logging.getLogger(__name__)

# MIME types we consider as possible direct receipt files
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_PDF_TYPE = "application/pdf"

# ── Fast receipt pre-filter ────────────────────────────────────────────────────
# Keywords that strongly suggest a receipt/invoice email
_RECEIPT_SUBJECT_KEYWORDS = [
    # Hebrew
    "קבלה", "חשבונית", "חיוב", "אישור הזמנה", "אישור תשלום",
    "הזמנה", "רכישה", "תשלום", "פקטורה",
    # English
    "receipt", "invoice", "order confirmation", "payment confirmation",
    "payment receipt", "your order", "purchase", "charged", "billing",
    "transaction", "paid",
]

_RECEIPT_BODY_KEYWORDS = [
    "₪", "nis", "total", "סכום", "לתשלום", "סה\"כ", "מחיר",
    "amount due", "amount paid", "subtotal", "grand total",
    "order total", "charged", "בוצע חיוב",
]

# Regex for monetary amounts: ₪123, $99.99, 1,234 ₪ etc.
import re as _re
_MONEY_RE = _re.compile(
    r"(?:₪|\$|€|£|USD|ILS|EUR)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*(?:₪|nis|ils)",
    _re.IGNORECASE,
)


def is_likely_receipt(email: "EmailMessage", threshold: int = 2) -> bool:
    """
    Fast pre-filter: score the email on cheap text signals.
    Returns True only if score >= threshold (default: 2 signals needed).

    Scoring:
     +3  PDF attachment
     +2  Image attachment (jpg/png)
     +2  Subject has a receipt keyword
     +1  Body has a receipt keyword
     +2  Body contains a monetary amount (₪99, $19.99 etc.)
    """
    score = 0

    # Attachment bonus (fastest check)
    for att in email.attachments:
        if att.mime_type == _PDF_TYPE:
            score += 3
            break
        if att.mime_type in _IMAGE_TYPES:
            score += 2
            break

    if score >= threshold:
        return True

    # Subject keyword check
    subj_lower = email.subject.lower()
    if any(kw.lower() in subj_lower for kw in _RECEIPT_SUBJECT_KEYWORDS):
        score += 2

    if score >= threshold:
        return True

    # Plain-text body checks (no rendering needed)
    body = (email.body_text or email.body_html or "").lower()

    if any(kw.lower() in body for kw in _RECEIPT_BODY_KEYWORDS):
        score += 1

    if _MONEY_RE.search(body):
        score += 2

    return score >= threshold


@dataclass
class ExtractedReceipt:
    data: bytes
    mime_type: str        # e.g. "application/pdf" or "image/jpeg"
    source: str           # "pdf_attachment" | "image_attachment" | "html_body"
    filename_hint: str    # original filename or empty string


def extract_receipt(email: EmailMessage) -> ExtractedReceipt | None:
    """
    Try to extract a receipt from an email using the priority chain:
      PDF attachment → image attachment → HTML body → plain text.
    Returns None if nothing usable found.
    """
    # 1. PDF attachment
    for att in email.attachments:
        if att.mime_type == _PDF_TYPE:
            logger.info("Using PDF attachment: %s", att.filename)
            return ExtractedReceipt(
                data=att.data,
                mime_type=_PDF_TYPE,
                source="pdf_attachment",
                filename_hint=att.filename,
            )

    # 2. Image attachment
    for att in email.attachments:
        if att.mime_type in _IMAGE_TYPES:
            logger.info("Using image attachment: %s", att.filename)
            return ExtractedReceipt(
                data=att.data,
                mime_type=att.mime_type,
                source="image_attachment",
                filename_hint=att.filename,
            )

    # 3. HTML body → render as PDF
    if email.body_html:
        pdf_bytes = _html_to_pdf(email.body_html, email.subject)
        if pdf_bytes:
            logger.info("Rendered HTML body to PDF for: %s", email.subject)
            return ExtractedReceipt(
                data=pdf_bytes,
                mime_type=_PDF_TYPE,
                source="html_body",
                filename_hint="",
            )

    # 4. Plain text fallback
    if email.body_text:
        pdf_bytes = _text_to_pdf(email.body_text, email.subject)
        if pdf_bytes:
            return ExtractedReceipt(
                data=pdf_bytes,
                mime_type=_PDF_TYPE,
                source="html_body",
                filename_hint="",
            )

    logger.warning("No receipt content found in email: %s", email.subject)
    return None


def _html_to_pdf(html: str, title: str = "") -> bytes | None:
    """
    Convert HTML to PDF.
    Tries Playwright first (best quality), falls back to WeasyPrint.
    """
    # Try Playwright
    try:
        return _html_to_pdf_playwright(html)
    except Exception as exc:
        logger.warning("Playwright failed (%s), trying WeasyPrint...", exc)

    # Fallback: WeasyPrint
    try:
        return _html_to_pdf_weasyprint(html)
    except Exception as exc:
        logger.error("WeasyPrint also failed: %s", exc)
        return None


def _html_to_pdf_playwright(html: str) -> bytes:
    """Render HTML → PDF using Playwright headless Chromium."""
    from playwright.sync_api import sync_playwright  # type: ignore

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        pdf_bytes = page.pdf(format="A4", print_background=True)
        browser.close()
    return pdf_bytes


def _html_to_pdf_weasyprint(html: str) -> bytes:
    """Render HTML → PDF using WeasyPrint (pure Python fallback)."""
    from weasyprint import HTML  # type: ignore
    return HTML(string=html).write_pdf()


def _text_to_pdf(text: str, title: str = "") -> bytes | None:
    """Convert plain text to minimal HTML and then to PDF."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"<html><body><pre style='font-family:sans-serif'>{escaped}</pre></body></html>"
    return _html_to_pdf(html, title)
