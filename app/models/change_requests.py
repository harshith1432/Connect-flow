from datetime import datetime
from sqlalchemy.orm import relationship, backref
from app.extensions import db


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
