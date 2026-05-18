"""
Voice Message Generator for Placement Notifications
Uses Microsoft Edge TTS (edge-tts) for high-quality neural voices
"""

try:
    from app.common.translation.translator import translate_message, get_language_code

    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    translate_message = None
    get_language_code = None


class VoiceGenerator:
    """Provides language mapping for Hooman Labs agents and Edge TTS preview audio generation"""

    def __init__(self):
        self.translator_available = TRANSLATOR_AVAILABLE
        if TRANSLATOR_AVAILABLE:
            print("[INFO] Translation module available - multilingual support enabled")
        else:
            print("[WARNING] Translation module not available")

    # Map 2-letter codes to Hooman full codes
    HOOMAN_LANG_MAP = {
        "hi": "hi-IN",
        "en": "en-IN",
        "ta": "ta-IN",
        "kn": "kn-IN",
        "te": "te-IN",
        "mr": "mr-IN",
        "pa": "pa-IN",
        "gu": "gu-IN",
        "ml": "ml-IN",
    }

    # Map 2-letter codes to high-quality Microsoft Edge-TTS voices
    EDGE_VOICE_MAP = {
        "hi": "hi-IN-MadhurNeural",
        "en": "en-IN-NeerjaNeural",
        "ta": "ta-IN-PallaviNeural",
        "kn": "kn-IN-SapnaNeural",
        "te": "te-IN-ShrutiNeural",
        "mr": "mr-IN-AarohiNeural",
        "pa": "pa-IN-GurvinderNeural",
        "gu": "gu-IN-DhwaniNeural",
        "ml": "ml-IN-SobhanaNeural",
    }

    def get_hooman_agent(self, language_code):
        """Get Hooman Labs Agent ID for a language code"""
        full_code = self.HOOMAN_LANG_MAP.get(language_code, language_code)

        from flask import current_app

        config_map = {
            "hi-IN": "HOOMAN_AGENT_HINDI",
            "en-IN": "HOOMAN_AGENT_ENGLISH",
            "ta-IN": "HOOMAN_AGENT_TAMIL",
            "kn-IN": "HOOMAN_AGENT_KANNADA",
            "te-IN": "HOOMAN_AGENT_TELUGU",
            "mr-IN": "HOOMAN_AGENT_MARATHI",
            "pa-IN": "HOOMAN_AGENT_PUNJABI",
            "gu-IN": "HOOMAN_AGENT_GUJARATI",
            "ml-IN": "HOOMAN_AGENT_MALAYALAM",
        }

        config_key = config_map.get(full_code)
        if config_key:
            agent_id = current_app.config.get(config_key)
            if agent_id:
                return agent_id
        return None

    async def generate_audio(self, text, language_code, output_path):
        """Generate audio using Edge TTS for preview purposes"""
        import edge_tts

        voice = self.EDGE_VOICE_MAP.get(language_code)
        if not voice:
            rev_map = {v[:2]: v for k, v in self.HOOMAN_LANG_MAP.items()}
            voice = rev_map.get(language_code[:2], "en-IN-NeerjaNeural")

        print(
            f"DEBUG: [TTS] Generating preview with voice {voice} for text: {text[:30]}..."
        )
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return output_path

    def cleanup_old_audio_files(self, days=1):
        """Placeholder for cleanup if needed by app.py"""
        pass


_voice_generator = None


def get_voice_generator():
    global _voice_generator
    if _voice_generator is None:
        _voice_generator = VoiceGenerator()
    return _voice_generator
