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
