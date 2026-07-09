import os
from datetime import timedelta
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv

load_dotenv(override=True)

class BaseConfig:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY must be set in environment variables.")

    # Core Application
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", BASE_URL)
    
    # Session / Security
    _env_secure = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _env_secure
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _env_secure
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=20)
    
    # Database default setup
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # Platform Admins
    DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL", "")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD", "")

    # Twilio Integration
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER", os.environ.get("DEFAULT_TWILIO_NUMBER", ""))
    TWILIO_VOICE_NUMBER = os.environ.get("TWILIO_VOICE_NUMBER", os.environ.get("TWILIO_PHONE_NUMBER", ""))
    DEFAULT_TWILIO_NUMBER = TWILIO_WHATSAPP_NUMBER
    BOT_SERVER_URL = os.environ.get("BOT_SERVER_URL", "")

    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_DISCOVERY_URL = os.environ.get("GOOGLE_DISCOVERY_URL", "https://accounts.google.com/.well-known/openid-configuration")

    # Hooman Labs
    HOOMAN_ORGANIZATION_ID = os.environ.get("HOOMAN_ORGANIZATION_ID", "")
    HOOMAN_CAMPAIGN_ID = os.environ.get("HOOMAN_CAMPAIGN_ID", "")
    HOOMAN_AGENT_ENGLISH = os.environ.get("HOOMAN_AGENT_ENGLISH", "")
    HOOMAN_AGENT_HINDI = os.environ.get("HOOMAN_AGENT_HINDI", "")
    # Add other regional agents...

    # Razorpay
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

    # hCaptcha (using official test keys as fallback for local dev if empty)
    HCAPTCHA_SITEKEY = os.environ.get("HCAPTCHA_SITEKEY") or "10000000-ffff-ffff-ffff-000000000001"
    HCAPTCHA_SECRET = os.environ.get("HCAPTCHA_SECRET") or "0x0000000000000000000000000000000000000000"

    @staticmethod
    def _parse_db_url(url: str, is_local: bool = False) -> str:
        if not url:
            return ""
        if url.startswith("sqlite:/") and not url.startswith("sqlite:///"):
            url = url.replace("sqlite:/", "sqlite:///")
        
        try:
            parsed = urlparse(url)
            if parsed.scheme.startswith("postgres"):
                qs = parse_qs(parsed.query)
                if not is_local and "sslmode" not in qs:
                    qs["sslmode"] = ["require"]
                    new_query = urlencode(qs, doseq=True)
                    parsed = parsed._replace(query=new_query)
                return urlunparse(parsed)
            return url
        except Exception:
            return url

class DevelopmentConfig(BaseConfig):
    """Development configuration."""
    DEBUG = True
    TESTING = False
    
    # ALWAYS use official test keys in local development so the widget actually displays on localhost
    HCAPTCHA_SITEKEY = "10000000-ffff-ffff-ffff-000000000001"
    HCAPTCHA_SECRET = "0x0000000000000000000000000000000000000000"
    
    SQLALCHEMY_DATABASE_URI = BaseConfig._parse_db_url(
        os.environ.get("DATABASE_URL", "sqlite:///instance/dev.db"), 
        is_local=True
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_ECHO = True

class TestingConfig(BaseConfig):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    
    WTF_CSRF_ENABLED = False
    PRESERVE_CONTEXT_ON_EXCEPTION = False

class StagingConfig(BaseConfig):
    """Staging configuration."""
    DEBUG = False
    TESTING = False
    
    SQLALCHEMY_DATABASE_URI = BaseConfig._parse_db_url(os.environ.get("DATABASE_URL"))
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 5,
        "max_overflow": 10,
        "connect_args": {"sslmode": "require"}
    }
    
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

class ProductionConfig(BaseConfig):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    
    SQLALCHEMY_DATABASE_URI = BaseConfig._parse_db_url(os.environ.get("DATABASE_URL"))
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 20,
        "max_overflow": 40,
        "connect_args": {"sslmode": "require"}
    }
    
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    
    'default': DevelopmentConfig
}

Config = BaseConfig

