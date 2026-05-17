from datetime import datetime
from enum import Enum
from flask_login import UserMixin

# Use db.JSON for portability across SQLite/Postgres
from sqlalchemy.orm import relationship, backref

from . import db
from werkzeug.security import generate_password_hash, check_password_hash


class Role(Enum):
    super_admin = "super_admin"
    org_admin = "org_admin"
    worker = "worker"


class PlatformAdmin(UserMixin, db.Model):
    __tablename__ = "platform_admin"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def create_default():
        from config import Config

        p = PlatformAdmin(
            email=Config.DEFAULT_ADMIN_EMAIL,
            password_hash=generate_password_hash(Config.DEFAULT_ADMIN_PASSWORD),
        )
        return p

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role(self):
        return "platform_owner"


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


class OrganizationUser(UserMixin, db.Model):
    __tablename__ = "organization_users"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    full_name = db.Column(db.String(255))
    email = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default=Role.worker.value)
    designation = db.Column(db.String(100))  # Job title / Role name
    phone = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Real-time Activity Tracking
    last_login = db.Column(db.DateTime)
    login_count = db.Column(db.Integer, default=0)
    performance_score = db.Column(db.Float, default=0.0)
    status_active = db.Column(db.Boolean, default=True)

    # Ensure (email, organization_id) is unique, not just email
    __table_args__ = (
        db.UniqueConstraint("email", "organization_id", name="_user_email_org_uc"),
    )

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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


class Module(db.Model):
    __tablename__ = "modules"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("organization_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    creator = relationship("OrganizationUser", foreign_keys=[created_by_id])

    fields = relationship("ModuleField", backref="module", cascade="all, delete-orphan")
    groups = relationship("ModuleGroup", backref="module", cascade="all, delete-orphan")


class ModuleGroup(db.Model):
    __tablename__ = "module_groups"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    records = relationship(
        "ModuleRecord", backref="group", cascade="all, delete-orphan"
    )
    scripts = relationship("Script", backref="group", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", backref="group", cascade="all, delete-orphan")


class ModuleField(db.Model):
    __tablename__ = "module_fields"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    name = db.Column(db.String(255), nullable=False)
    field_type = db.Column(db.String(50), default="string")
    is_unique = db.Column(db.Boolean, default=False)
    meta = db.Column(db.JSON)

    group = relationship(
        "ModuleGroup", backref=backref("fields", cascade="all, delete-orphan")
    )

    @property
    def options(self):
        """Returns a list of options for dropdown/multiple choice fields."""
        if not self.meta:
            return []
        import json

        if isinstance(self.meta, str):
            try:
                meta_dict = json.loads(self.meta)
            except:
                return []
        else:
            meta_dict = self.meta
        return meta_dict.get("options", [])


class ModuleRecord(db.Model):
    __tablename__ = "module_records"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("organization_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    values = relationship(
        "ModuleRecordValue", backref="record", cascade="all, delete-orphan"
    )

    @property
    def field_values(self):
        """Returns a dictionary mapping field_id to its value."""
        return {v.field_id: v.value for v in self.values}

    @property
    def named_values(self):
        """Returns a dictionary mapping field name to its value."""
        return {v.field.name: v.value for v in self.values if v.field}


class ModuleRecordValue(db.Model):
    __tablename__ = "module_record_values"
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(
        db.Integer, db.ForeignKey("module_records.id", ondelete="CASCADE")
    )
    field_id = db.Column(
        db.Integer, db.ForeignKey("module_fields.id", ondelete="CASCADE")
    )
    value = db.Column(db.Text)

    field = db.relationship("ModuleField", foreign_keys=[field_id])


class Contact(db.Model):
    __tablename__ = "contacts"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name = db.Column(db.String(255))
    phone = db.Column(db.String(100))
    preferred_language = db.Column(db.String(50), default="English")
    meta = db.Column(db.JSON)


class ContactGroup(db.Model):
    __tablename__ = "contact_groups"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name = db.Column(db.String(255))


class ContactGroupMap(db.Model):
    __tablename__ = "contact_group_map"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(
        db.Integer, db.ForeignKey("contact_groups.id", ondelete="CASCADE")
    )
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id", ondelete="CASCADE"))


class Script(db.Model):
    __tablename__ = "scripts"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    language = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # whatsapp_text, call
    content = db.Column(db.Text, nullable=False)
    meta = db.Column(db.JSON)


class Campaign(db.Model):
    __tablename__ = "campaigns"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="SET NULL"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(
        db.String(50), nullable=False
    )  # whatsapp_text, whatsapp_voice, call
    script_id = db.Column(db.Integer, db.ForeignKey("scripts.id", ondelete="SET NULL"))
    sender_number_id = db.Column(
        db.Integer, db.ForeignKey("communication_numbers.id", ondelete="SET NULL")
    )
    filters = db.Column(db.JSON)
    status = db.Column(db.String(50), default="draft")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("organization_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    targets = relationship(
        "CampaignTarget", backref="campaign", cascade="all, delete-orphan"
    )


class CampaignTarget(db.Model):
    __tablename__ = "campaign_targets"
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id", ondelete="CASCADE"))
    status = db.Column(db.String(50), default="queued")


class DeliveryLog(db.Model):
    __tablename__ = "delivery_logs"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    contact_id = db.Column(
        db.Integer, db.ForeignKey("contacts.id", ondelete="SET NULL")
    )
    channel = db.Column(db.String(50))
    sid = db.Column(db.String(100), index=True)  # Twilio MessageSid or CallSid
    recipient = db.Column(db.String(100))  # Recipient phone number
    status = db.Column(db.String(50))
    error = db.Column(db.Text)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Plan(db.Model):
    __tablename__ = "plans"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), default=0.00)
    billing_interval = db.Column(db.String(50), default="monthly")  # monthly, yearly
    features = db.Column(db.JSON)  # List of strings or key-value pairs
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": float(self.price) if self.price else 0.0,
            "billing_interval": self.billing_interval,
            "features": self.features,
            "is_active": self.is_active,
        }


class PaymentMethod(db.Model):
    __tablename__ = "payment_methods"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # UPI, Stripe, Bank Transfer, etc.
    type = db.Column(db.String(50), default="manual")  # gateway, manual
    instructions = db.Column(db.Text)
    config = db.Column(db.JSON)  # API keys for gateways or Bank details
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "instructions": self.instructions,
            "is_active": self.is_active,
        }


class ChangeRequest(db.Model):
    __tablename__ = "change_requests"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("organization_users.id"), nullable=True
    )
    field_name = db.Column(
        db.String(100), nullable=False
    )  # e.g., 'org_name', 'admin_email'
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    status = db.Column(db.String(50), default="pending")  # pending, approved, rejected
    admin_note = db.Column(db.Text)  # Note from Org Admin to Platform Admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)

    # Relationships
    organization = db.relationship("Organization", foreign_keys=[organization_id])
    user = db.relationship("OrganizationUser", foreign_keys=[user_id])

    @staticmethod
    def log(org_id, user_id, action, old_val=None, new_val=None, status="approved"):
        activity = ChangeRequest(
            organization_id=org_id,
            user_id=user_id,
            field_name=action,
            old_value=str(old_val) if old_val else None,
            new_value=str(new_val) if new_val else None,
            status=status,
        )
        db.session.add(activity)
        db.session.commit()
        return activity


class PlatformNotification(db.Model):
    __tablename__ = "platform_notifications"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    type = db.Column(
        db.String(50), nullable=False
    )  # 'info_change', 'number_request', 'alert'
    title = db.Column(db.String(255))
    message = db.Column(db.Text)
    link = db.Column(db.String(500))  # Optional URL to navigate to
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    organization_rel = relationship(
        "Organization", backref=backref("notifications", cascade="all, delete-orphan")
    )


class PlatformSecurity(db.Model):
    __tablename__ = "platform_security"
    id = db.Column(db.Integer, primary_key=True)
    default_admin_enabled = db.Column(db.Boolean, default=True)

    @staticmethod
    def get_settings():
        settings = PlatformSecurity.query.first()
        if not settings:
            settings = PlatformSecurity(default_admin_enabled=True)
            db.session.add(settings)
            db.session.commit()
        return settings
