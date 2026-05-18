from datetime import datetime
from enum import Enum
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


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
        from app.config import Config

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
