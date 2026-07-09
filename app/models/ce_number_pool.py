"""
Campaign Express Number Pool Model
Manages platform-owned communication numbers used exclusively for CE campaign execution.
CE users never see or select these numbers — allocation is fully automatic.
"""
from datetime import datetime
from app.extensions import db


class CeNumberPool(db.Model):
    """A platform-owned communication number available for CE campaign execution."""
    __tablename__ = "ce_number_pool"

    id            = db.Column(db.Integer, primary_key=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    label         = db.Column(db.String(100), nullable=False)   # Admin-friendly name
    number        = db.Column(db.String(30),  nullable=False)   # E.164 or plain format
    channel_type  = db.Column(db.String(30),  default="voice")  # voice | whatsapp_text | whatsapp_voice

    # ── Provider Config ───────────────────────────────────────────────────────
    provider      = db.Column(db.String(50),  default="twilio")  # twilio | hooman | custom
    api_token     = db.Column(db.Text)                           # Provider API token / SID
    auth_token    = db.Column(db.Text)                           # Provider auth token
    webhook_url   = db.Column(db.String(500))                    # Optional override webhook

    # ── State ─────────────────────────────────────────────────────────────────
    is_active     = db.Column(db.Boolean, default=True)
    is_healthy    = db.Column(db.Boolean, default=True)          # Health monitor flag

    # ── Load Balancing ────────────────────────────────────────────────────────
    # Tracks concurrent campaigns using this number for round-robin / least-loaded
    active_campaigns_count = db.Column(db.Integer, default=0)
    total_campaigns_served = db.Column(db.Integer, default=0)
    total_calls_made       = db.Column(db.Integer, default=0)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at  = db.Column(db.DateTime, nullable=True)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes         = db.Column(db.Text)

    def __repr__(self):
        return f"<CeNumberPool {self.label} [{self.number}] active={self.is_active}>"

    @property
    def status_label(self):
        if not self.is_active:
            return "Disabled"
        if not self.is_healthy:
            return "Unhealthy"
        return "Active"

    @property
    def status_class(self):
        if not self.is_active:
            return "bg-secondary"
        if not self.is_healthy:
            return "bg-warning text-dark"
        return "bg-success"


class CeCampaignNumberAssignment(db.Model):
    """
    Tracks which pool number is assigned to each CE campaign execution.
    Allows audit trail and capacity management.
    """
    __tablename__ = "ce_campaign_number_assignments"

    id            = db.Column(db.Integer, primary_key=True)
    campaign_id   = db.Column(db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"))
    pool_number_id = db.Column(db.Integer, db.ForeignKey("ce_number_pool.id", ondelete="SET NULL"), nullable=True)

    assigned_at   = db.Column(db.DateTime, default=datetime.utcnow)
    released_at   = db.Column(db.DateTime, nullable=True)
    status        = db.Column(db.String(30), default="active")  # active | released | failed

    pool_number = db.relationship("CeNumberPool", backref="assignments")

    def __repr__(self):
        return f"<CeCampaignAssignment campaign={self.campaign_id} number={self.pool_number_id}>"
