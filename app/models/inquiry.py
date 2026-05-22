from app.extensions import db
from datetime import datetime


class Inquiry(db.Model):
    """Leads generated from 'Talk to Us' form on the public landing pages."""
    __tablename__ = "inquiries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    company_name = db.Column(db.String(200), nullable=True)
    reason = db.Column(db.String(100), nullable=True)       # e.g. "Demo", "Pricing", "Partnership"
    message = db.Column(db.Text, nullable=True)
    source_page = db.Column(db.String(100), nullable=True)  # which page they came from
    status = db.Column(db.String(30), default="New")        # New | Contacted | Qualified | Closed
    admin_remark = db.Column(db.Text, nullable=True)        # Platform admin notes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Inquiry {self.name} <{self.email}> [{self.status}]>"
