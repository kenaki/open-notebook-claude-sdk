"""Shared upload helpers.

Factored out of ``api/routers/sources.py`` so the chat-media endpoints (and any
future uploader) can reuse the same unique-naming, save, and path-traversal-guard
logic against a configurable target folder instead of copying it.
"""

import os
from pathlib import Path

from fastapi import UploadFile
from loguru import logger

from open_notebook.config import UPLOADS_FOLDER


def generate_unique_filename(original_filename: str, upload_folder: str) -> str:
    """Generate unique filename like Streamlit app (append counter if file exists)."""
    file_path = Path(upload_folder)
    file_path.mkdir(parents=True, exist_ok=True)

    # Strip directory components to prevent path traversal
    safe_filename = os.path.basename(original_filename)
    if not safe_filename:
        raise ValueError("Invalid filename")

    # Split filename and extension
    stem = Path(safe_filename).stem
    suffix = Path(safe_filename).suffix

    # Check if file exists and generate unique name
    counter = 0
    while True:
        if counter == 0:
            new_filename = safe_filename
        else:
            new_filename = f"{stem} ({counter}){suffix}"

        full_path = file_path / new_filename
        # Verify resolved path stays within upload folder
        resolved = full_path.resolve()
        if not str(resolved).startswith(str(file_path.resolve()) + os.sep):
            raise ValueError("Invalid filename: path traversal detected")
        if not resolved.exists():
            return str(resolved)
        counter += 1


async def save_uploaded_file(
    upload_file: UploadFile, upload_folder: str = UPLOADS_FOLDER
) -> str:
    """Save uploaded file to ``upload_folder`` and return the file path.

    Defaults to the main uploads folder so existing source-upload callers are
    unaffected; pass ``CHAT_MEDIA_FOLDER`` (etc.) to route elsewhere.
    """
    if not upload_file.filename:
        raise ValueError("No filename provided")

    # Generate unique filename
    file_path = generate_unique_filename(upload_file.filename, upload_folder)

    try:
        # Save file
        with open(file_path, "wb") as f:
            content = await upload_file.read()
            f.write(content)

        logger.info(f"Saved uploaded file to: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        # Clean up partial file if it exists
        if os.path.exists(file_path):
            os.unlink(file_path)
        raise


def resolve_audio_path(audio_file: str) -> Path:
    """Resolve an audio_file string (plain path or file:// URI) to a Path."""
    if audio_file.startswith("file://"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(audio_file)
        return Path(unquote(parsed.path))
    return Path(audio_file)


def resolve_upload_file(file_path: str) -> tuple[str, str]:
    """Validate file_path is within UPLOADS_FOLDER and exists; return (resolved_path, filename).

    Raises PermissionError if the path escapes UPLOADS_FOLDER.
    Raises FileNotFoundError if the file does not exist.
    """
    safe_root = os.path.realpath(UPLOADS_FOLDER)
    resolved_path = os.path.realpath(file_path)
    if not resolved_path.startswith(safe_root):
        raise PermissionError(f"Path escapes upload directory: {resolved_path}")
    if not os.path.exists(resolved_path):
        raise FileNotFoundError(f"File not found: {resolved_path}")
    return resolved_path, os.path.basename(resolved_path)


def resolve_within(folder: str, filename: str) -> str:
    """Resolve ``filename`` inside ``folder`` with a path-traversal guard.

    Mirrors the guard in ``sources.py`` ``_resolve_source_file``: strips directory
    components, resolves real paths, and verifies the result stays under ``folder``.
    Returns the resolved absolute path (existence is the caller's concern).
    Raises ``ValueError`` if the name escapes the folder.
    """
    safe_name = os.path.basename(filename)
    if not safe_name:
        raise ValueError("Invalid filename")

    safe_root = os.path.realpath(folder)
    resolved = os.path.realpath(os.path.join(safe_root, safe_name))
    if resolved != safe_root and not resolved.startswith(safe_root + os.sep):
        raise ValueError("Invalid filename: path traversal detected")
    return resolved
