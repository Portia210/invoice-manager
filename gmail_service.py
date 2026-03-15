"""
gmail_service.py — Gmail API helpers for receipt scanning.

Uses the same OAuth2 token as drive_service.py (shared scopes).
"""

from __future__ import annotations
import base64
import logging
from email import message_from_bytes
from email.message import Message
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator

from googleapiclient.discovery import build, Resource

from config import GOOGLE_SCOPES, CREDENTIALS_PATH

logger = logging.getLogger(__name__)

# Gmail search query — catches receipts from major sources in Hebrew + English
RECEIPT_QUERY = (
    "in:inbox newer_than:365d "
    "("
    "קבלה OR חשבונית OR receipt OR invoice OR payment OR "
    "order OR הזמנה OR חיוב OR אישור OR confirmation OR "
    "וולט OR פייפאל OR paypal OR אמזון OR amazon OR "
    "ביט OR bit OR כרטיס OR charged OR paid"
    ")"
)


@dataclass
class EmailAttachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass
class EmailMessage:
    msg_id: str
    subject: str
    sender: str
    date_str: str
    body_html: str
    body_text: str
    attachments: list[EmailAttachment] = field(default_factory=list)


@lru_cache(maxsize=1)
def get_gmail_service() -> Resource:
    """Return authenticated Gmail API service (shares token with Drive)."""
    from drive_service import _load_credentials  # reuse same auth flow
    creds = _load_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    logger.info("Gmail service initialised.")
    return service


def list_receipt_message_ids(
    service: Resource,
    exclude_ids: set[str] | None = None,
) -> list[str]:
    """
    Return Gmail message IDs matching RECEIPT_QUERY, excluding already-processed ones.
    """
    exclude_ids = exclude_ids or set()
    msg_ids: list[str] = []
    next_page: str | None = None

    while True:
        kwargs: dict = {"userId": "me", "q": RECEIPT_QUERY, "maxResults": 500}
        if next_page:
            kwargs["pageToken"] = next_page

        resp = service.users().messages().list(**kwargs).execute()
        for m in resp.get("messages", []):
            if m["id"] not in exclude_ids:
                msg_ids.append(m["id"])

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    logger.info("Found %d new candidate emails.", len(msg_ids))
    return msg_ids


def fetch_email(service: Resource, msg_id: str) -> EmailMessage:
    """Fetch a full email and parse headers, body, and attachments."""
    raw = (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="raw")
        .execute()
    )
    raw_bytes = base64.urlsafe_b64decode(raw["raw"] + "==")
    msg: Message = message_from_bytes(raw_bytes)

    subject = _decode_header(msg.get("Subject", ""))
    sender = _decode_header(msg.get("From", ""))
    date_str = msg.get("Date", "")

    body_html = ""
    body_text = ""
    attachments: list[EmailAttachment] = []

    for part in msg.walk():
        ct = part.get_content_type()
        cd = str(part.get("Content-Disposition", ""))
        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        if "attachment" in cd or part.get_filename():
            fname = _decode_header(part.get_filename() or "attachment")
            attachments.append(EmailAttachment(
                filename=fname,
                mime_type=ct,
                data=payload,
            ))
        elif ct == "text/html" and not body_html:
            body_html = payload.decode(part.get_content_charset("utf-8"), errors="replace")
        elif ct == "text/plain" and not body_text:
            body_text = payload.decode(part.get_content_charset("utf-8"), errors="replace")

    return EmailMessage(
        msg_id=msg_id,
        subject=subject,
        sender=sender,
        date_str=date_str,
        body_html=body_html,
        body_text=body_text,
        attachments=attachments,
    )


def _decode_header(value: str) -> str:
    """Decode RFC-2047 encoded email header."""
    from email.header import decode_header
    parts = decode_header(value)
    decoded = []
    for part_bytes, charset in parts:
        if isinstance(part_bytes, bytes):
            decoded.append(part_bytes.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part_bytes)
    return "".join(decoded)
