from datetime import datetime
from sqlalchemy.orm import relationship, backref
from app.extensions import db

class Organization(db.Model):
    __tablename__ = "organizations"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # SaaS Profiling Fields
    org_type = db.Column(db.String(100))  # Company, Startup, Institute, etc.
    industry = db.Column(db.String(100))  # Education, IT, etc.
    country = db.Column(db.String(100))
    office_address = db.Column(db.Text)
    logo_url = db.Column(db.String(500))
    language_preference = db.Column(db.String(50), default="English")
    support_email = db.Column(db.String(255))
    support_phone = db.Column(db.String(50))

    # Verification System
    status = db.Column(db.String(50), default="pending")  # pending, active, suspended
    is_verified = db.Column(db.Boolean, default=False)

    # Custom Communication Config
    twilio_config = db.Column(db.JSON)  # {'voice': {...}, 'whatsapp': {...}}
    hooman_config = db.Column(
        db.JSON
    )  # {'secret_token': '...', 'number': '+91...', 'api_key': '...'}
    # Granular default access control
    allow_default_voice = db.Column(db.Boolean, default=True)
    allow_default_whatsapp = db.Column(db.Boolean, default=True)
    allow_default_access = db.Column(
        db.Boolean, default=True
    )  # Deprecated but kept for safety during migration
    whatsapp_channel_type = db.Column(
        db.String(50), default="whatsapp", nullable=False
    )  # 'whatsapp' or 'whatsapp_business'

    # Preferences
    notification_prefs = db.Column(db.JSON)  # email, mobile, etc.
    backup_frequency = db.Column(db.String(50), default="daily")
    data_retention_days = db.Column(db.Integer, default=365)

    users = relationship("OrganizationUser", backref="organization")
    modules = relationship("Module", backref="organization")


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    plan = db.Column(db.String(100), default="Free Tier")
    status = db.Column(
        db.String(50), default="active"
    )  # active, past_due, canceled, suspended
    billing_interval = db.Column(db.String(50), default="monthly")  # monthly, yearly

    starts_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    last_alert_sent_at = db.Column(db.DateTime)

    billing_name = db.Column(db.String(255))
    billing_email = db.Column(db.String(255))
    billing_address = db.Column(db.Text)
    payment_method = db.Column(db.String(100))  # Card, UPI, etc.
    meta = db.Column(db.JSON)

    @property
    def is_expired(self):
        from datetime import datetime

        if self.status == "inactive":
            return True
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        return False

    @property
    def display_status(self):
        if self.status == "inactive":
            return "INACTIVE"
        from datetime import datetime

        if self.expires_at and datetime.utcnow() > self.expires_at:
            return "EXPIRED"
        return self.status.upper()


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    amount = db.Column(db.Numeric)
    status = db.Column(db.String(50))
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CommunicationNumber(db.Model):
    __tablename__ = "communication_numbers"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    number = db.Column(db.String(100), nullable=False)
    channel_type = db.Column(
        db.String(20), nullable=True, default="voice"
    )  # 'voice' or 'whatsapp'
    is_platform_owned = db.Column(db.Boolean, default=False)
    approved = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    meta = db.Column(db.JSON)
