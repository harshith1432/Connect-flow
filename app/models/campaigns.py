from datetime import datetime
from sqlalchemy.orm import relationship, backref
from app.extensions import db


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
