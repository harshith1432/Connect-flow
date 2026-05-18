from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import check_password_hash
from app.extensions import db
from .platform import Role


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
