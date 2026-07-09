from datetime import datetime
from app.extensions import db

class PaymentVerification(db.Model):
    __tablename__ = "payment_verifications"
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), nullable=False)  # Plan ID or Campaign ID
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    generated_upi_id = db.Column(db.String(100), nullable=False)
    transaction_id = db.Column(db.String(255), unique=True, nullable=False)
    screenshot_path = db.Column(db.String(500), nullable=False)
    customer_upi_id = db.Column(db.String(100))
    submitted_time = db.Column(db.DateTime, default=datetime.utcnow)
    verification_time = db.Column(db.DateTime)
    verified_by = db.Column(db.String(255))
    status = db.Column(db.String(50), default="pending")  # pending, approved, rejected
    remarks = db.Column(db.Text)
    ip_address = db.Column(db.String(100))
    device_info = db.Column(db.Text)
    audit_log = db.Column(db.JSON, default=list)

    # Relationship to organization (optional)
    organization = db.relationship("Organization", backref="verifications")

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "organization_id": self.organization_id,
            "organization_name": self.organization.name if self.organization else None,
            "amount": float(self.amount),
            "generated_upi_id": self.generated_upi_id,
            "transaction_id": self.transaction_id,
            "screenshot_path": self.screenshot_path,
            "customer_upi_id": self.customer_upi_id,
            "submitted_time": self.submitted_time.isoformat() if self.submitted_time else None,
            "verification_time": self.verification_time.isoformat() if self.verification_time else None,
            "verified_by": self.verified_by,
            "status": self.status,
            "remarks": self.remarks,
            "ip_address": self.ip_address,
            "device_info": self.device_info,
            "audit_log": self.audit_log
        }
