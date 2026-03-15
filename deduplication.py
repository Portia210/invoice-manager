"""
deduplication.py — MD5 hashing and metadata.json management in Google Drive.
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
    return files[0]["id"] if files else None


def load_metadata(service: "Resource", folder_id: str) -> tuple[dict, str | None]:
    """
    Load metadata.json from Google Drive.

    Returns:
        (metadata_dict, file_id_or_None)
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
) -> None:
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
    else:
        file_metadata = {
            "name": METADATA_FILENAME,
            "parents": [folder_id],
        }
        (
            service.files()
            .create(body=file_metadata, media_body=media, supportsAllDrives=True)
            .execute()
        )
        logger.debug("Created metadata.json in folder %s", folder_id)


def is_duplicate(md5_hash: str, metadata: dict) -> bool:
    """Return True if this hash already exists in the metadata store."""
    return md5_hash in metadata.get("hashes", {})


def record_file(md5_hash: str, filename: str, drive_link: str, metadata: dict) -> dict:
    """Add a processed file record to the metadata dict and return it."""
    if "hashes" not in metadata:
        metadata["hashes"] = {}
    metadata["hashes"][md5_hash] = {
        "original_filename": filename,
        "drive_link": drive_link,
    }
    return metadata
