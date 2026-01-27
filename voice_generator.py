"""
Voice Message Generator for Placement Notifications
Uses Microsoft Edge TTS (edge-tts) for high-quality neural voices
"""
import os
import asyncio
import threading
from pathlib import Path
import uuid

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    print("[WARNING] edge-tts not installed. Install with: pip install edge-tts")

# Import translator module
try:
    from translator import translate_message, get_language_code
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    print("[WARNING] translator module not found. Multilingual translation disabled.")
    translate_message = None
    get_language_code = None


class VoiceGenerator:
    """Generate voice messages for placement notifications with translation support"""
    
    # Mapping of language codes to specific Neural voices
    # Using Indian English (en-IN) and specific regional voices
    VOICE_MAPPING = {
        'en': 'en-IN-NeerjaNeural',      # English (India) - Female
        'hi': 'hi-IN-SwaraNeural',       # Hindi - Female
        'kn': 'kn-IN-SapnaNeural',       # Kannada - Female
        'ta': 'ta-IN-PallaviNeural',     # Tamil - Female
        'te': 'te-IN-ShrutiNeural',      # Telugu - Female
        'ml': 'ml-IN-SobhanaNeural',     # Malayalam - Female
        'gu': 'gu-IN-DhwaniNeural',      # Gujarati - Female
        'mr': 'mr-IN-AarohiNeural',      # Marathi - Female
        'bn': 'bn-IN-TanishaaNeural',    # Bengali - Female
        'pa': 'pa-IN-OjasNeural',        # Punjabi - Male (Female sometimes not available)
        'or': 'or-IN-MunaNeural',        # Odia - Male
        'ur': 'ur-IN-GulNeural',         # Urdu (India) - Female
    }

    def __init__(self, audio_dir='static/audio'):
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.edge_tts_available = EDGE_TTS_AVAILABLE
        self.translator_available = TRANSLATOR_AVAILABLE
        
        if EDGE_TTS_AVAILABLE:
            print("[INFO] Neural voice generator (edge-tts) initialized successfully")
        else:
            print("[ERROR] edge-tts not available - voice generation disabled")
        
        if TRANSLATOR_AVAILABLE:
            print("[INFO] Translation module available - multilingual support enabled")
        else:
            print("[WARNING] Translation module not available - using English messages only")
    
    def get_voice_for_language(self, language_code):
        """Get the specific neural voice for a language code"""
        # Default to English (India) if language not found
        return self.VOICE_MAPPING.get(language_code, 'en-IN-NeerjaNeural')
    
    async def _generate_audio_async(self, text, voice, output_path):
        """Internal async method to generate audio"""
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
    
    def generate_placement_message(self, student_name, company_name, package, 
                                   mother_tongue='English', student_id=1):
        """
        Generate a placement notification voice message using Neural TTS
        
        Args:
            student_name: Student's full name
            company_name: Company name
            package: Salary package (e.g., "25 LPA")
            mother_tongue: Student's mother tongue (e.g., 'Kannada', 'Tamil', 'English')
            student_id: Student ID for unique filename
        
        Returns:
            dict: Result details including file path
        """
        try:
            if not self.edge_tts_available:
                return {
                    'success': False,
                    'file_path': None, 
                    'error': 'edge-tts not available'
                }
            
            # Step 1: Create English message
            english_message = f"Congratulations! Your child {student_name} has been placed in {company_name} with a package of {package} LPA. Congratulations to the entire family!"
            
            # Step 2: Translate message
            translated_text = english_message
            lang_code = 'en'
            lang_name = 'English'
            
            if self.translator_available and translate_message and mother_tongue.lower() != 'english':
                translated_text, lang_code, lang_name = translate_message(english_message, mother_tongue)
            
            # Step 3: Select Neural Voice
            voice = self.get_voice_for_language(lang_code)
            print(f"[INFO] Using voice {voice} for {lang_name} ({lang_code})")
            
            # Step 4: Generate audio file
            # Generate a unique filename using hex to avoid caching issues and collisions
            audio_filename = f'placement_msg_{student_id}_{uuid.uuid4().hex[:8]}_{lang_code}.mp3'
            audio_path = self.audio_dir / audio_filename
            
            # Run async generation in a blocking way (since we are in a synchronous context)
            try:
                # Create a fresh event loop for this operation if needed, 
                # or use asyncio.run if not already in a loop.
                # Since this might be called from Flask (wsgi), asyncio.run is usually safe.
                asyncio.run(self._generate_audio_async(translated_text, voice, str(audio_path)))
            except Exception as e:
                # Fallback for complex loop situations (e.g. if already in loop)
                print(f"[WARNING] Standard asyncio.run failed: {e}. Trying alternate loop handling.")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._generate_audio_async(translated_text, voice, str(audio_path)))
                loop.close()
            
            # Verify file
            if not audio_path.exists():
                return {
                    'success': False,
                    'error': 'Audio file creation failed'
                }
            
            file_size = audio_path.stat().st_size
            print(f"[SUCCESS] Voice message generated: {audio_filename} ({file_size} bytes)")
            
            return {
                'success': True,
                'file_path': str(audio_path),
                'filename': audio_filename,
                'file_size': file_size,
                'language': lang_code,
                'language_name': lang_name,
                'original_text': english_message,
                'translated_text': translated_text,
                'voice_used': voice,
                'error': None
            }
                
        except Exception as e:
            print(f"[ERROR] Error generating neural voice message: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'original_text': '',
                'translated_text': ''
            }
    
    def generate_generic_voice_message(self, text, language='en'):
        """
        Generate a generic voice message from text
        """
        try:
            if not self.edge_tts_available:
                return {'success': False, 'error': 'edge-tts not available'}
                
            filename = f"voice_{uuid.uuid4().hex}_{language}.mp3"
            audio_path = self.audio_dir / filename
            
            voice = self.get_voice_for_language(language)
            
            asyncio.run(self._generate_audio_async(text, voice, str(audio_path)))
            
            if not audio_path.exists():
                return {'success': False, 'error': 'File creation failed'}
                
            return {
                'success': True, 
                'file_path': str(audio_path),
                'filename': filename,
                'file_size': audio_path.stat().st_size
            }
        except Exception as e:
            print(f"[ERROR] Generic voice gen failed: {e}")
            return {'success': False, 'error': str(e)}

    def stop(self):
        pass


def create_placement_notification_voice(student_data, audio_dir='static/audio'):
    """
    Helper function to create voice notification
    """
    try:
        voice_gen = VoiceGenerator(audio_dir)
        return voice_gen.generate_placement_message(
            student_name=student_data.get('full_name', 'Student'),
            company_name=student_data.get('company_name', 'Company'),
            package=student_data.get('package', 'Package'),
            mother_tongue=student_data.get('mother_tongue', 'English'),
            student_id=student_data.get('id', 1)
        )
    except Exception as e:
        print(f"[ERROR] Helper function error: {e}")
        return {'success': False, 'error': str(e)}


# Global instance
_voice_generator = None

def get_voice_generator():
    global _voice_generator
    if _voice_generator is None:
        _voice_generator = VoiceGenerator()
    return _voice_generator


if __name__ == '__main__':
    # Test voice generation
    generator = get_voice_generator()
    
    print("\n" + "="*70)
    print("Testing Neural Voice Generation")
    print("="*70)
    
    test_students = [
        {'id': 1, 'full_name': 'Harshith', 'company_name': 'Google', 'package': '25', 'mother_tongue': 'Kannada'},
        {'id': 2, 'full_name': 'Priya', 'company_name': 'Microsoft', 'package': '23', 'mother_tongue': 'Tamil'},
        {'id': 3, 'full_name': 'Raj', 'company_name': 'TCS', 'package': '20', 'mother_tongue': 'Hindi'},
    ]
    
    for student in test_students:
        result = create_placement_notification_voice(student)
        if result['success']:
            print(f"\n✅ {student['mother_tongue']} ({result['voice_used']}):")
            print(f"   File: {result['filename']}")
        else:
            print(f"\n❌ {student['mother_tongue']}: {result['error']}")