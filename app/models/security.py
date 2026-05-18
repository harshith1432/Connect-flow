from datetime import datetime
from app.extensions import db

class MfaConfiguration(db.Model):
    __tablename__ = "mfa_configurations"
    id = db.Column(db.Integer, primary_key=True)
    user_type = db.Column(db.String(50), nullable=False)  # 'platform_admin' or 'org_user'
    user_id = db.Column(db.Integer, nullable=False)
    mfa_type = db.Column(db.String(50), default="none")  # 'email', 'sms', 'totp', 'none'
    secret_key = db.Column(db.String(255), nullable=True)  # for TOTP
    is_enabled = db.Column(db.Boolean, default=False)
    backup_codes = db.Column(db.JSON, nullable=True)  # recovery codes list
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_type", "user_id", name="_user_mfa_uc"),
    )


class OtpVerification(db.Model):
    __tablename__ = "otp_verifications"
    id = db.Column(db.Integer, primary_key=True)
    user_type = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    otp_code = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(50), default="login")  # 'login', 'reset_password'
    mfa_method = db.Column(db.String(50), nullable=False)  # 'email', 'sms', 'totp'
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    attempts = db.Column(db.Integer, default=0)
    resend_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActiveSession(db.Model):
    __tablename__ = "active_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_type = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    session_token = db.Column(db.String(255), unique=True, nullable=False)
    ip_address = db.Column(db.String(100), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    browser = db.Column(db.String(100), nullable=True)
    device = db.Column(db.String(100), nullable=True)
    os = db.Column(db.String(100), nullable=True)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SecurityAuditLog(db.Model):
    __tablename__ = "security_audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_type = db.Column(db.String(50), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    organization_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(100), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    severity = db.Column(db.String(50), default="low")  # 'low', 'medium', 'high', 'critical'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SuspiciousActivity(db.Model):
    __tablename__ = "suspicious_activities"
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(100), nullable=True)
    user_type = db.Column(db.String(50), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    email = db.Column(db.String(255), nullable=True)
    activity_type = db.Column(db.String(100), nullable=False)  # 'brute_force', 'unusual_ip', 'mfa_bypass_attempt'
    details = db.Column(db.Text, nullable=True)
    resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
