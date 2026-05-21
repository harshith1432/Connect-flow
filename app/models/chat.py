from datetime import datetime
from app.extensions import db

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    sender_type = db.Column(db.String(50), nullable=False)  # 'platform_admin', 'org_admin', 'worker'
    sender_id = db.Column(db.Integer, nullable=False)
    recipient_type = db.Column(db.String(50), nullable=False)  # 'platform_admin', 'org_admin', 'worker'
    recipient_id = db.Column(db.Integer, nullable=False)
    organization_id = db.Column(db.Integer, nullable=True)  # Scoped organization ID
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_edited = db.Column(db.Boolean, default=False, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    reactions = db.Column(db.Text, nullable=True)  # Stores JSON string: {"user_id_role": "emoji"}

    def to_dict(self):
        import json
        parsed_reactions = {}
        if self.reactions:
            try:
                parsed_reactions = json.loads(self.reactions)
            except Exception:
                parsed_reactions = {}

        return {
            "id": self.id,
            "sender_type": self.sender_type,
            "sender_id": self.sender_id,
            "recipient_type": self.recipient_type,
            "recipient_id": self.recipient_id,
            "organization_id": self.organization_id,
            "message": self.message,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() + "Z",
            "is_edited": self.is_edited,
            "is_deleted": self.is_deleted,
            "reactions": parsed_reactions
        }

class DashboardNotification(db.Model):
    __tablename__ = "dashboard_notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)  # Targets OrganizationUser
    platform_admin_id = db.Column(db.Integer, nullable=True)  # Targets PlatformAdmin
    organization_id = db.Column(db.Integer, nullable=True)  # Scoped organization ID
    type = db.Column(db.String(50), nullable=False)  # 'chat', 'system', 'campaign', 'billing'
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "platform_admin_id": self.platform_admin_id,
            "organization_id": self.organization_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "link": self.link,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() + "Z"
        }
