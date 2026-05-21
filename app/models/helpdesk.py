from datetime import datetime
import random
from app.extensions import db

class HelpdeskQuery(db.Model):
    __tablename__ = "helpdesk_queries"
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(50), unique=True, nullable=False)
    user_type = db.Column(db.String(50), nullable=False)  # 'org_admin', 'worker'
    user_id = db.Column(db.Integer, nullable=False)  # OrganizationUser ID
    organization_id = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default="Pending")  # 'Pending', 'Resolved'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        from app.models import OrganizationUser, Organization
        user = OrganizationUser.query.get(self.user_id)
        org = Organization.query.get(self.organization_id)
        return {
            "id": self.id,
            "ticket_number": self.ticket_number,
            "user_type": self.user_type,
            "user_id": self.user_id,
            "user_name": user.full_name or user.email if user else "Unknown User",
            "user_email": user.email if user else "N/A",
            "organization_id": self.organization_id,
            "organization_name": org.name if org else "Unknown Organization",
            "message": self.message,
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "resolved_at": (self.resolved_at.isoformat() + "Z") if self.resolved_at else None
        }

    @staticmethod
    def generate_ticket_number():
        # Generate HD-YYYYMMDD-XXXX where XXXX is random number
        date_str = datetime.utcnow().strftime("%Y%m%d")
        rand_num = random.randint(1000, 9999)
        return f"HD-{date_str}-{rand_num}"
