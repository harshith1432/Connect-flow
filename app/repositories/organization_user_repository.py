from typing import Optional, List
from app.repositories.base import BaseRepository
from app.models.worker import OrganizationUser
from app.extensions import db

class OrganizationUserRepository(BaseRepository[OrganizationUser]):
    def __init__(self):
        super().__init__(OrganizationUser)
    
    def get_by_email_and_org(self, email: str, org_id: int) -> Optional[OrganizationUser]:
        return self.model_class.query.filter_by(email=email, organization_id=org_id).first()
    
    def get_workers_by_org(self, org_id: int) -> List[OrganizationUser]:
        return self.model_class.query.filter_by(organization_id=org_id).all()
