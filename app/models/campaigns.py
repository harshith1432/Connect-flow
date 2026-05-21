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
    max_retry = db.Column(db.Integer, default=1)

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
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    record_id = db.Column(db.Integer, db.ForeignKey("module_records.id", ondelete="CASCADE"), nullable=True)
    # Statuses: queued | calling | waiting_webhook | answered
    #           retry_pending | retrying | whatsapp_sent | completed | failed
    status = db.Column(db.String(50), default="queued")
    call_attempts = db.Column(db.Integer, default=0)
    retry_count = db.Column(db.Integer, default=0)        # increments only on retry
    next_retry_at = db.Column(db.DateTime, nullable=True) # set when retry_pending
    last_call_status = db.Column(db.String(50))
    last_attempt_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime, nullable=True)  # when terminal status reached
    whatsapp_sent = db.Column(db.Boolean, default=False)
    whatsapp_text_sid  = db.Column(db.String(100))   # SID of the text message
    voice_sid    = db.Column(db.String(100))          # SID of the audio message
    voice_file   = db.Column(db.String(500))          # local MP3 path
    voice_sent   = db.Column(db.Boolean, default=False)
    voice_status = db.Column(db.String(50))           # queued|sent|failed|partial_success
    external_task_id = db.Column(db.String(100), index=True)

    # HoomanLabs integration columns
    call_status = db.Column(db.String(50))
    connected = db.Column(db.Boolean, default=False)
    attempt = db.Column(db.Integer, default=1)
    conversation_id = db.Column(db.String(100), index=True)
    duration = db.Column(db.Integer)
    summary = db.Column(db.Text)
    transcript = db.Column(db.Text)
    end_reason = db.Column(db.Text)
    last_webhook_at = db.Column(db.DateTime)
    event_hash = db.Column(db.String(64), unique=True)


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
        db.Integer, db.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    record_id = db.Column(
        db.Integer, db.ForeignKey("module_records.id", ondelete="SET NULL"), nullable=True
    )
    channel = db.Column(db.String(50))
    sid = db.Column(db.String(100), index=True)  # Twilio MessageSid or CallSid
    recipient = db.Column(db.String(100))  # Recipient phone number
    status = db.Column(db.String(50))
    error = db.Column(db.Text)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CallTargetResult(db.Model):
    __tablename__ = "call_target_results"
    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("campaign_targets.id", ondelete="CASCADE"))
    attempt_number = db.Column(db.Integer, default=1)
    connected = db.Column(db.Boolean, default=False)
    duration = db.Column(db.Integer, default=0)
    outcome = db.Column(db.String(100))
    end_reason = db.Column(db.Text)
    transcript = db.Column(db.Text)
    summary = db.Column(db.Text)
    conversation_id = db.Column(db.String(100), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    target = relationship("CampaignTarget", backref=backref("results", cascade="all, delete-orphan"))
