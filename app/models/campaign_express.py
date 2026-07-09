from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import db


class CampaignExpressUser(UserMixin, db.Model):
    """
    Standalone user model for Campaign Express.
    Independent from OrganizationUser — no org_id required.
    """
    __tablename__ = "campaign_express_users"

    id = db.Column(db.Integer, primary_key=True)

    # ── Basic Profile ──────────────────────────────────────────────────────────
    first_name    = db.Column(db.String(100))
    last_name     = db.Column(db.String(100))
    username      = db.Column(db.String(100), unique=True, nullable=False)
    email         = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))   # nullable for Google-only users
    profile_photo = db.Column(db.String(500))
    campaign_purpose = db.Column(db.String(100))  # Marketing / Events / Education / etc.
    preferences   = db.Column(db.JSON)

    # ── Google OAuth ───────────────────────────────────────────────────────────
    google_id     = db.Column(db.String(200), unique=True, nullable=True)
    auth_provider = db.Column(db.String(20), default="manual")  # "manual" | "google"

    # ── Address ───────────────────────────────────────────────────────────────
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city          = db.Column(db.String(100))
    state         = db.Column(db.String(100))
    country       = db.Column(db.String(100))
    postal_code   = db.Column(db.String(20))

    # ── Identity / Verification ───────────────────────────────────────────────
    identity_type     = db.Column(db.String(50))
    identity_number   = db.Column(db.String(100))
    identity_document = db.Column(db.String(500))  # path to uploaded file

    # Verification state machine:
    #   profile_created → verification_pending → verified
    verification_status = db.Column(db.String(50), default="profile_created")

    # ── Activity Tracking ─────────────────────────────────────────────────────
    role                 = db.Column(db.String(30), default="campaign_express")
    is_active            = db.Column(db.Boolean, default=True)
    onboarding_completed = db.Column(db.Boolean, default=False)

    def get_id(self):
        return f"campaign_express_user:{self.id}"
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)
    last_login           = db.Column(db.DateTime)
    login_count          = db.Column(db.Integer, default=0)

    # ── Relationships ─────────────────────────────────────────────────────────
    payments = db.relationship(
        "CampaignExpressPayment",
        backref="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        parts = [self.first_name or "", self.last_name or ""]
        return " ".join(p for p in parts if p).strip() or self.username

    @property
    def is_verified(self):
        return self.verification_status == "verified"

    @property
    def display_verification_label(self):
        mapping = {
            "profile_created":     "Profile Incomplete",
            "verification_pending": "Verification Pending",
            "verified":            "Verified",
        }
        return mapping.get(self.verification_status, self.verification_status.replace("_", " ").title())

    @property
    def verification_badge_class(self):
        mapping = {
            "profile_created":     "bg-warning text-dark",
            "verification_pending": "bg-info text-dark",
            "verified":            "bg-success",
        }
        return mapping.get(self.verification_status, "bg-secondary")

    def __repr__(self):
        return f"<CampaignExpressUser {self.email} [{self.verification_status}]>"


class CampaignExpressPayment(db.Model):
    """
    Per-campaign payment record for Campaign Express users.
    Uses the same gateway infrastructure as the org Payment model.
    """
    __tablename__ = "campaign_express_payments"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("campaign_express_users.id", ondelete="CASCADE"))
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    amount      = db.Column(db.Float, nullable=False)
    currency    = db.Column(db.String(10), default="INR")

    # Status: pending | completed | failed | refunded
    status      = db.Column(db.String(30), default="pending")

    # ── Gateway info (mirrors Payment model fields) ───────────────────────────
    gateway_id          = db.Column(db.Integer, db.ForeignKey("payment_gateways.id", ondelete="SET NULL"), nullable=True)
    gateway_name        = db.Column(db.String(100))
    gateway_provider    = db.Column(db.String(50))   # 'razorpay' | 'stripe'
    gateway_mode        = db.Column(db.String(20))   # 'test' | 'live'
    transaction_id      = db.Column(db.String(255))  # e.g. razorpay_payment_id
    gateway_response    = db.Column(db.JSON)         # full gateway response

    notes       = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationship
    gateway = db.relationship("PaymentGateway", foreign_keys=[gateway_id])

    def __repr__(self):
        return f"<CampaignExpressPayment campaign={self.campaign_id} amount={self.amount} status={self.status}>"
