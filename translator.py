"""
Translation Module for Placement Notifications
Translates placement messages into student's mother tongue
Supports both online (googletrans) and offline translation
"""

import re

try:
    from deep_translator import GoogleTranslator

    TRANSLATOR_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    TRANSLATOR_AVAILABLE = False
    print(
        "[WARNING] deep-translator not available. Install with: pip install deep-translator"
    )
    print("[INFO] Using built-in translations for common messages...")

# Pre-built translations for common placement messages
# This acts as fallback when googletrans is not available
PREBUILT_TRANSLATIONS = {
    "en": (
        "Congratulations. Your child {name} has been selected for a job at "
        "{company} with a package of {package} lakh rupees."
    ),
    "kn": (
        "ಅಭಿನಂದನೆಗಳು. ನಿಮ್ಮ ಮಗುವಾದ {name} ಅವರು {company} ಸಂಸ್ಥೆಯಲ್ಲಿ "
        "{package} ಲಕ್ಷ ರೂಪಾಯಿಗಳ ಪ್ಯಾಕೇಜ್ ನೊಂದಿಗೆ ಉದ್ಯೋಗಕ್ಕೆ ಆಯ್ಕೆಯಾಗಿದ್ದಾರೆ."
    ),
    "ta": (
        "வாழ்த்துக்கள். உங்கள் குழந்தை {name} அவர்கள் {company} நிறுவனத்தில் "
        "{package} லட்சம் ரூபாய் சம்பளத்தில் வேலைக்கு தேர்வு செய்யப்பட்டுள்ளார்."
    ),
    "hi": (
        "बधाई हो. आपके बच्चे {name} को {company} कंपनी में "
        "{package} लाख रुपये के पैकेज के साथ नौकरी मिली है."
    ),
    "te": (
        "అభినందనలు. మీ బిడ్డ {name} గారు {company} సంస్థలో "
        "{package} లక్షల రూపాయల ప్యాకేజీతో ఉద్యోగానికి ఎంపికయ్యారు."
    ),
    "ml": (
        "അഭിനന്ദനങ്ങൾ. നിങ്ങളുടെ മകൻ അല്ലെങ്കിൽ മകൾ {name} "
        "{company} സ്ഥാപനത്തിൽ {package} ലക്ഷത്തിന്റെ പാക്കേജോടെ ജോലി ലഭിച്ചിട്ടുണ്ട്."
    ),
    "gu": (
        "અભિનંદન. તમારા બાળક {name} ને {company} કંપનીમાં "
        "{package} લાખ રૂપિયાના પેકેજ સાથે નોકરી મળી છે."
    ),
    "mr": (
        "अभिनंदन. आपल्या मुलगा किंवा मुलगी {name} यांची {company} कंपनीत "
        "{package} लाख रुपयांच्या पॅकेजसह निवड झाली आहे."
    ),
    "pa": (
        "ਮੁਬਾਰਕਾਂ. ਤੁਹਾਡੇ ਬੱਚੇ {name} ਦੀ {company} ਕੰਪਨੀ ਵਿੱਚ "
        "{package} ਲੱਖ ਰੁਪਏ ਦੇ ਪੈਕੇਜ ਨਾਲ ਚੋਣ ਹੋਈ ਹੈ."
    ),
    "bn": (
        "অভিনন্দন. আপনার সন্তান {name} {company} কোম্পানিতে "
        "{package} লক্ষ টাকার প্যাকেজসহ চাকরি পেয়েছেন."
    ),
    "or": (
        "ଅଭିନନ୍ଦନ. ଆପଣଙ୍କ ସନ୍ତାନ {name}ଙ୍କୁ {company} କମ୍ପାନୀରେ "
        "{package} ଲକ୍ଷ ଟଙ୍କାର ପ୍ୟାକେଜ ସହିତ ଚାକିରି ମିଳିଛି."
    ),
}


# Language code mapping (ISO 639-1 to full language names)
LANGUAGE_MAP = {
    "en": {"code": "en", "name": "English", "native": "English"},
    "hi": {"code": "hi", "name": "Hindi", "native": "हिंदी"},
    "ka": {"code": "kn", "name": "Kannada", "native": "ಕನ್ನಡ"},
    "kn": {"code": "kn", "name": "Kannada", "native": "ಕನ್ನಡ"},
    "ta": {"code": "ta", "name": "Tamil", "native": "தமிழ்"},
    "te": {"code": "te", "name": "Telugu", "native": "తెలుగు"},
    "ml": {"code": "ml", "name": "Malayalam", "native": "മലയാളം"},
    "gu": {"code": "gu", "name": "Gujarati", "native": "ગુજરાતી"},
    "mr": {"code": "mr", "name": "Marathi", "native": "मराठी"},
    "pa": {"code": "pa", "name": "Punjabi", "native": "ਪੰਜਾਬੀ"},
    "bn": {"code": "bn", "name": "Bengali", "native": "বাংলা"},
    "or": {"code": "or", "name": "Odia", "native": "ଓଡ଼ିଆ"},
}

# Note: deep-translator doesn't require a global translator instance


def get_language_code(mother_tongue):
    """
    Convert mother tongue to language code for translation

    Args:
        mother_tongue (str): Mother tongue value (e.g., 'Kannada', 'en', 'ka', 'kn')

    Returns:
        str: Language code for translation (e.g., 'kn', 'hi', 'ta')
    """
    if not mother_tongue:
        return "en"

    mother_tongue = mother_tongue.strip().lower()

    # Direct code lookup
    if mother_tongue in LANGUAGE_MAP:
        return LANGUAGE_MAP[mother_tongue]["code"]

    # Fuzzy matching by name
    for code, info in LANGUAGE_MAP.items():
        if mother_tongue == info["name"].lower():
            return info["code"]
        if mother_tongue == info["native"].lower():
            return info["code"]

    # Default to English if not found
    print(f"[WARNING] Language '{mother_tongue}' not recognized, defaulting to English")
    return "en"


def translate_message(text, mother_tongue):
    """
    Translate placement message to student's mother tongue

    Args:
        text (str): Original message in English with {name}, {company}, {package} placeholders
        mother_tongue (str): Student's mother tongue (e.g., 'Kannada', 'Tamil')

    Returns:
        tuple: (translated_text, language_code, language_name)
        or (original_text, 'en', 'English') if translation fails
    """
    try:
        # Get language code
        lang_code = get_language_code(mother_tongue)

        # English to English - no translation needed
        if lang_code == "en":
            print(f"[INFO] Using English message (no translation needed)")
            return text, "en", "English"

        # Try online translation first
        if TRANSLATOR_AVAILABLE:
            try:
                print(
                    f"[INFO] Translating message to {LANGUAGE_MAP.get(lang_code, {}).get('name', lang_code)} using Google Translate..."
                )

                # deep-translator uses a different API
                translator = GoogleTranslator(source="en", target=lang_code)
                translated_text = translator.translate(text)

                lang_name = LANGUAGE_MAP.get(lang_code, {}).get("name", lang_code)

                print(f"[SUCCESS] Message translated successfully to {lang_name}")
                print(f"[ORIGINAL] {text}")
                print(f"[TRANSLATED] {translated_text}")

                return translated_text, lang_code, lang_name
            except Exception as e:
                print(f"[WARNING] Online translation failed: {str(e)}")
                print(f"[INFO] Falling back to pre-built translations...")

        # Fallback to pre-built translations
        if lang_code in PREBUILT_TRANSLATIONS:
            print(
                f"[INFO] Using pre-built translation for {LANGUAGE_MAP.get(lang_code, {}).get('name', lang_code)}"
            )
            # Get the pre-built template and replace placeholders with actual values from the English message
            translated_text = PREBUILT_TRANSLATIONS[lang_code]

            # Extract values from the English message to fill in placeholders
            # The English message format is: "Congratulations! Your child {name} has been placed in {company} with a package of {package} LPA..."

            # Try to extract name, company, package from the text
            name_match = re.search(r"Your child\s+([^,]+)\s+has been", text)
            company_match = re.search(r"placed in\s+([^,]+)\s+with a package", text)
            package_match = re.search(r"package of\s+([^,]+?)\s+LPA", text)

            name = name_match.group(1) if name_match else "Student"
            company = company_match.group(1) if company_match else "Company"
            package = package_match.group(1) if package_match else "Package"

            # Replace placeholders in the translated text
            translated_text = translated_text.format(
                name=name, company=company, package=package
            )

            lang_name = LANGUAGE_MAP.get(lang_code, {}).get("name", lang_code)

            print(f"[SUCCESS] Message translated successfully to {lang_name}")
            print(f"[ORIGINAL] {text[:60]}...")
            print(f"[TRANSLATED] {translated_text[:60]}...")

            return translated_text, lang_code, lang_name

        # If no translation available, use English
        print(f"[WARNING] No translation available for {lang_code}")
        return text, "en", "English"

    except Exception as e:
        print(f"[WARNING] Translation failed: {str(e)}")
        print(f"[INFO] Using English message as fallback")
        return text, "en", "English"


def create_placement_script(student_name, company_name, package):
    """
    Create the placement notification script in English

    Args:
        student_name (str): Student's full name
        company_name (str): Company name
        package (str): Salary package (e.g., "25 LPA")

    Returns:
        str: Formatted placement message
    """
    message = f"Congratulations! Your child {student_name} has been placed in {company_name} with a package of {package} LPA. Congratulations to the entire family!"
    return message


def test_translator():
    """Test the translator with sample messages"""
    print("\n" + "=" * 70)
    print("Testing Translation Module")
    print("=" * 70)

    test_message = "Congratulations! Your child Harshith has been placed in Google with a package of 25 LPA. Congratulations to the entire family!"
    languages = ["en", "ka", "hi", "ta", "te", "ml"]

    for lang in languages:
        translated, code, name = translate_message(test_message, lang)
        print(f"\n{name}:")
        print(f"  Translated: {translated[:80]}...")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_translator()
