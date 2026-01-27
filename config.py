import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from dotenv import load_dotenv
import os as _os

# Load environment variables from .env (if present) and also from services/.env
# This helps when credentials are stored in a services-specific dotenv file (e.g., during development).
load_dotenv(override=True)


class Config:
    # Core
    # Use provided SECRET_KEY in production; fall back to a stable dev key for local testing
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-change-me'

    # Database - require DATABASE_URL in environment/.env
    _raw_db = os.environ.get('DATABASE_URL')
    if not _raw_db:
        raise RuntimeError('DATABASE_URL must be set in environment or .env')

    # Normalize common local sqlite env values that may be missing slashes
    if _raw_db.startswith('sqlite:/') and not _raw_db.startswith('sqlite:///'):
        _raw_db = _raw_db.replace('sqlite:/', 'sqlite:///')

    # Ensure sslmode=require is present for PostgreSQL connections (Neon)
    try:
        parsed = urlparse(_raw_db)
        # only handle postgres schemes
        if parsed.scheme.startswith('postgres'):
            qs = parse_qs(parsed.query)
            if 'sslmode' not in qs:
                qs['sslmode'] = ['require']
                new_query = urlencode(qs, doseq=True)
                parsed = parsed._replace(query=new_query)
            SQLALCHEMY_DATABASE_URI = urlunparse(parsed)
        else:
            # For sqlite or other non-postgres URLs, keep the original string
            SQLALCHEMY_DATABASE_URI = _raw_db
    except Exception:
        # fallback—use raw
        SQLALCHEMY_DATABASE_URI = _raw_db

    # Pass engine options only for Postgres; avoid invalid args for sqlite
    if parsed.scheme.startswith('postgres'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"sslmode": "require"},
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 10,
            "max_overflow": 20,
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Twilio - read from environment (.env loaded above)
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    
    # Separate numbers for Voice and WhatsApp to allow using Sandbox for WA and Verified Number for Voice
    TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER', os.environ.get('DEFAULT_TWILIO_NUMBER', ''))
    TWILIO_VOICE_NUMBER = os.environ.get('TWILIO_VOICE_NUMBER', os.environ.get('TWILIO_PHONE_NUMBER', ''))
    
    # Legacy fallback (maintained for backward compatibility)
    DEFAULT_TWILIO_NUMBER = TWILIO_WHATSAPP_NUMBER  
    # Optional custom WhatsApp bot server URL (platform config)
    BOT_SERVER_URL = os.environ.get('BOT_SERVER_URL', '')

    # Default platform admin boot credentials (managed via .env)
    DEFAULT_ADMIN_EMAIL = os.environ.get('DEFAULT_ADMIN_EMAIL', '')
    DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', '')

    # App URLs
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')
    # Session / security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV', '').lower() == 'production'
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
