import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from dotenv import load_dotenv

load_dotenv(override=True)


class Config:
    # Core
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-change-me"

    # Database
    _raw_db = os.environ.get("DATABASE_URL")
    if not _raw_db:
        raise RuntimeError("DATABASE_URL must be set in environment or .env")

    if _raw_db.startswith("sqlite:/") and not _raw_db.startswith("sqlite:///"):
        _raw_db = _raw_db.replace("sqlite:/", "sqlite:///")

    try:
        parsed = urlparse(_raw_db)
        is_local = parsed.hostname in ("localhost", "127.0.0.1")

        if parsed.scheme.startswith("postgres"):
            qs = parse_qs(parsed.query)
            if not is_local and "sslmode" not in qs:
                qs["sslmode"] = ["require"]
                new_query = urlencode(qs, doseq=True)
                parsed = parsed._replace(query=new_query)
            SQLALCHEMY_DATABASE_URI = urlunparse(parsed)
        else:
            SQLALCHEMY_DATABASE_URI = _raw_db
    except Exception:
        SQLALCHEMY_DATABASE_URI = _raw_db
        is_local = False

    if parsed.scheme.startswith("postgres"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 10,
            "max_overflow": 20,
        }
        if not is_local:
            SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = {"sslmode": "require"}
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Twilio
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")

    TWILIO_WHATSAPP_NUMBER = os.environ.get(
        "TWILIO_WHATSAPP_NUMBER", os.environ.get("DEFAULT_TWILIO_NUMBER", "")
    )
    TWILIO_VOICE_NUMBER = os.environ.get(
        "TWILIO_VOICE_NUMBER", os.environ.get("TWILIO_PHONE_NUMBER", "")
    )

    DEFAULT_TWILIO_NUMBER = TWILIO_WHATSAPP_NUMBER
    BOT_SERVER_URL = os.environ.get("BOT_SERVER_URL", "")

    DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL", "")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD", "")

    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

    # Session / security
    from datetime import timedelta

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=20)

    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_DISCOVERY_URL = os.environ.get(
        "GOOGLE_DISCOVERY_URL",
        "https://accounts.google.com/.well-known/openid-configuration",
    )

    # Hooman Labs Agents
    HOOMAN_AGENT_HINDI = os.environ.get("HOOMAN_AGENT_HINDI", "")
    HOOMAN_AGENT_ENGLISH = os.environ.get("HOOMAN_AGENT_ENGLISH", "")
    HOOMAN_AGENT_TAMIL = os.environ.get("HOOMAN_AGENT_TAMIL", "")
    HOOMAN_AGENT_KANNADA = os.environ.get("HOOMAN_AGENT_KANNADA", "")
    HOOMAN_AGENT_TELUGU = os.environ.get("HOOMAN_AGENT_TELUGU", "")
    HOOMAN_CAMPAIGN_ID = os.environ.get("HOOMAN_CAMPAIGN_ID", "AvltYGFZt3IDKEsX9uO7")

    HOOMAN_AGENT_MARATHI = os.environ.get("HOOMAN_AGENT_MARATHI", "")
    HOOMAN_AGENT_PUNJABI = os.environ.get("HOOMAN_AGENT_PUNJABI", "")
    HOOMAN_AGENT_GUJARATI = os.environ.get("HOOMAN_AGENT_GUJARATI", "")
    HOOMAN_AGENT_MALAYALAM = os.environ.get("HOOMAN_AGENT_MALAYALAM", "")
    HOOMAN_AGENT_VOICE_CALL = os.environ.get("HOOMAN_AGENT_VOICE_CALL", "")
    HOOMAN_ORGANIZATION_ID = os.environ.get("HOOMAN_ORGANIZATION_ID", "")
