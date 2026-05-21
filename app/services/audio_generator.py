"""
audio_generator.py
──────────────────
Converts plain text into an MP3 audio file for WhatsApp media attachment delivery.

Strategy:
  1. Try edge-tts  (neural, natural voices — requires internet)
  2. Fallback to gTTS (simple but reliable)

No FFmpeg required.  The MP3 is sent directly as a WhatsApp media attachment
(appears as a playable audio file in the chat).

Supported languages:
  English, Hindi, Kannada, Tamil, Telugu, Malayalam, Gujarati,
  Marathi, Punjabi, Bengali, Odia

Output: MP3 saved to  static/audio/voice_notes/<filename>.mp3
        codec:        mp3
        sample rate:  44100 Hz  (edge-tts default; gTTS default)
        channels:     mono
        bitrate:      128 k

Auto-cleanup: files older than 24 h are deleted on every generation call.
"""

import os
import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Audio storage directory ────────────────────────────────────────────────────
_VOICE_DIR = Path(__file__).parent.parent / "static" / "audio" / "voice_notes"
_VOICE_DIR.mkdir(parents=True, exist_ok=True)

# ── Language → gTTS lang code ─────────────────────────────────────────────────
_GTTS_LANG = {
    "english":   "en",
    "hindi":     "hi",
    "kannada":   "kn",
    "tamil":     "ta",
    "telugu":    "te",
    "malayalam": "ml",
    "gujarati":  "gu",
    "marathi":   "mr",
    "punjabi":   "pa",
    "bengali":   "bn",
    "odia":      "or",
}

# ── Language → edge-tts voice name ────────────────────────────────────────────
_EDGE_VOICE = {
    # format: (female_voice, male_voice)
    "english":   ("en-IN-NeerjaNeural",    "en-IN-PrabhatNeural"),
    "hindi":     ("hi-IN-SwaraNeural",     "hi-IN-MadhurNeural"),
    "kannada":   ("kn-IN-SapnaNeural",     "kn-IN-GaganNeural"),
    "tamil":     ("ta-IN-PallaviNeural",   "ta-IN-ValluvarNeural"),
    "telugu":    ("te-IN-ShrutiNeural",    "te-IN-MohanNeural"),
    "malayalam": ("ml-IN-SobhanaNeural",   "ml-IN-MidhunNeural"),
    "gujarati":  ("gu-IN-DhwaniNeural",    "gu-IN-NiranjanNeural"),
    "marathi":   ("mr-IN-AarohiNeural",    "mr-IN-ManoharNeural"),
    "punjabi":   ("pa-IN-OjasNeural",      "pa-IN-OjasNeural"),   # limited voices
    "bengali":   ("bn-IN-TanishaaNeural",  "bn-IN-BashkarNeural"),
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _cleanup_old_files(max_age_hours: int = 24):
    """Delete MP3 files older than max_age_hours from the voice_notes folder."""
    cutoff = time.time() - max_age_hours * 3600
    deleted = 0
    for f in _VOICE_DIR.glob("campaign_*.mp3"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception:
            pass
    if deleted:
        logger.info("[AUDIO CLEANUP] Deleted %d stale MP3 file(s)", deleted)


def _safe_filename(campaign_id, target_id) -> str:
    """Build a safe, unique filename: campaign_<id>_target_<id>.mp3"""
    return f"campaign_{campaign_id}_target_{target_id}.mp3"


# ─────────────────────────────────────────────────────────────────────────────
# TTS BACKENDS
# ─────────────────────────────────────────────────────────────────────────────

async def _edge_tts_generate(text: str, voice: str, out_path: str) -> bool:
    """Generate MP3 audio via edge-tts (async). Returns True on success."""
    try:
        import edge_tts  # type: ignore
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_path)
        return True
    except Exception as exc:
        logger.warning("[AUDIO] edge-tts failed (%s) — will try gTTS fallback", exc)
        return False


def _gtts_generate(text: str, lang: str, out_path: str) -> bool:
    """Generate MP3 audio via gTTS. Returns True on success."""
    try:
        from gtts import gTTS  # type: ignore
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(out_path)
        return True
    except Exception as exc:
        logger.error("[AUDIO] gTTS also failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def generate_voice_note(
    text: str,
    campaign_id: int,
    target_id: int,
    language: str = "English",
    gender: str = "female",
) -> str | None:
    """
    Convert *text* to an MP3 audio file for WhatsApp media attachment delivery.

    Returns the absolute file path (.mp3) on success, or None on failure.

    Parameters
    ----------
    text        : The message body to speak (already variable-substituted).
    campaign_id : Used in the output filename.
    target_id   : Used in the output filename.
    language    : Script language string (e.g. "Kannada", "Hindi", "English").
    gender      : "female" (default) or "male".

    Output filename pattern:
        campaign_<campaign_id>_target_<target_id>.mp3

    Served at:
        <BASE_URL>/static/audio/voice_notes/campaign_<id>_target_<id>.mp3
        Content-Type: audio/mpeg
    """
    _cleanup_old_files()

    lang_key = language.strip().lower()
    mp3_name = _safe_filename(campaign_id, target_id)
    mp3_path = str(_VOICE_DIR / mp3_name)

    logger.info(
        "[AUDIO GENERATING] campaign=%s target=%s lang=%s gender=%s -> %s",
        campaign_id, target_id, lang_key, gender, mp3_name,
    )

    # ── Step 1: TTS → MP3 (edge-tts primary, gTTS fallback) ──────────────────
    voice_pair = _EDGE_VOICE.get(lang_key, _EDGE_VOICE["english"])
    edge_voice = voice_pair[0] if gender == "female" else voice_pair[1]

    tts_success = False
    try:
        loop = asyncio.new_event_loop()
        tts_success = loop.run_until_complete(
            _edge_tts_generate(text, edge_voice, mp3_path)
        )
        loop.close()
    except Exception as exc:
        logger.warning("[AUDIO] edge-tts event loop error: %s", exc)
        tts_success = False

    if not tts_success or not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 1000:
        gtts_lang   = _GTTS_LANG.get(lang_key, "en")
        tts_success = _gtts_generate(text, gtts_lang, mp3_path)

    if not tts_success or not os.path.exists(mp3_path):
        logger.error("[AUDIO FAILED] TTS produced no file for target=%s", target_id)
        return None

    mp3_size = os.path.getsize(mp3_path)
    if mp3_size < 500:
        logger.error(
            "[AUDIO FAILED] MP3 file too small (%d bytes) for target=%s — discarding",
            mp3_size, target_id,
        )
        try:
            os.remove(mp3_path)
        except Exception:
            pass
        return None

    logger.info("[AUDIO GENERATED] %s  (%d bytes)", mp3_name, mp3_size)
    return mp3_path
