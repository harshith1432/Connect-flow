"""
audio_service.py
----------------
Handles audio file saving and public URL generation for the campaign calling system.

- Files are saved under `static/uploads/`
- Public URLs are built using BASE_URL from .env (Cloudflare tunnel domain)
- Never generates localhost URLs
"""

import os
import uuid
import logging
from werkzeug.utils import secure_filename
from flask import current_app

logger = logging.getLogger(__name__)

# Allowed audio MIME extensions
ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "aac", "m4a", "webm", "flac"}


def _get_base_url() -> str:
    """
    Load BASE_URL from Flask app config (which reads from .env).
    Strips trailing slashes and whitespace.
    Raises ValueError if missing or falls back to localhost.
    """
    base_url = current_app.config.get("BASE_URL", "").strip().rstrip("/")

    if not base_url:
        raise ValueError(
            "BASE_URL is not set in .env. Cannot generate a public audio URL for Hooman Labs."
        )

    if "localhost" in base_url or "127.0.0.1" in base_url:
        raise ValueError(
            f"BASE_URL is set to a local address ({base_url}). "
            "Hooman Labs requires a publicly accessible URL (e.g. Cloudflare tunnel)."
        )

    return base_url


def allowed_file(filename: str) -> bool:
    """Check if the uploaded filename has an allowed audio extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_audio_file(file_storage, subfolder: str = "uploads") -> dict:
    """
    Save an uploaded audio file to `static/uploads/<subfolder>/` with a UUID-based unique name.

    Args:
        file_storage: Werkzeug FileStorage object (from request.files)
        subfolder:    Sub-directory inside static/uploads/ (default: 'uploads')

    Returns:
        {
            "filename":   "abc123_audio.mp3",         # unique saved filename
            "file_path":  "/abs/path/to/file.mp3",    # absolute filesystem path
            "static_rel": "uploads/abc123_audio.mp3", # path relative to static/
            "public_url": "https://tunnel.../static/uploads/abc123_audio.mp3"
        }

    Raises:
        ValueError: if file is missing, empty, or has a disallowed extension
    """
    if not file_storage or not file_storage.filename:
        raise ValueError("No audio file was provided in the upload request.")

    original_name = secure_filename(file_storage.filename)
    if not allowed_file(original_name):
        ext = original_name.rsplit(".", 1)[-1] if "." in original_name else "unknown"
        raise ValueError(
            f"File type '.{ext}' is not allowed. Supported formats: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Generate a UUID-prefixed filename to guarantee uniqueness
    unique_name = f"{uuid.uuid4().hex}_{original_name}"
    logger.debug(
        f"[AudioService] Original filename: {original_name} → Saved as: {unique_name}"
    )

    # Build save path: <static_folder>/uploads/<subfolder>/
    save_dir = os.path.join(current_app.static_folder, "uploads", subfolder)
    os.makedirs(save_dir, exist_ok=True)

    file_path = os.path.join(save_dir, unique_name)
    file_storage.save(file_path)
    logger.info(f"[AudioService] Audio file saved to: {file_path}")

    # Build the path relative to static/ for URL generation
    # e.g. "uploads/uploads/abc123_audio.mp3"
    static_rel = os.path.join("uploads", subfolder, unique_name).replace("\\", "/")

    # Generate public URL
    public_url = build_public_audio_url(static_rel)

    return {
        "filename": unique_name,
        "file_path": file_path,
        "static_rel": static_rel,
        "public_url": public_url,
    }


def build_public_audio_url(static_relative_path: str) -> str:
    """
    Generate a fully qualified public URL for a file stored under static/.

    Args:
        static_relative_path: path relative to static/, e.g. "audio/abc123.mp3"
                               or "uploads/uploads/abc123.mp3"

    Returns:
        Full public URL: "https://occupied-consumers-hang-atm.trycloudflare.com/static/audio/abc123.mp3"

    Raises:
        ValueError: if BASE_URL is missing or local
    """
    base_url = _get_base_url()
    # Ensure no double slashes
    clean_rel = static_relative_path.lstrip("/").replace("\\", "/")
    public_url = f"{base_url}/static/{clean_rel}"

    logger.debug(f"[AudioService] Generated public audio URL: {public_url}")
    return public_url


def build_tts_public_url(audio_filename: str) -> str:
    """
    Generate a public URL for a TTS-generated file stored in static/audio/.

    Args:
        audio_filename: just the filename, e.g. "voice_abc123.mp3"

    Returns:
        "https://tunnel.../static/audio/voice_abc123.mp3"
    """
    return build_public_audio_url(f"audio/{audio_filename}")
