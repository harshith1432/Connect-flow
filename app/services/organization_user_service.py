from typing import Dict, Any, Optional
from werkzeug.security import generate_password_hash
from app.services.base import BaseService
from app.repositories.organization_user_repository import OrganizationUserRepository
from app.models.worker import OrganizationUser

class OrganizationUserService(BaseService):
    def __init__(self):
        super().__init__(OrganizationUserRepository())
    
    def create_worker(self, org_id: int, data: Dict[str, Any], commit: bool = True) -> OrganizationUser:
        """Create a new worker for an organization, hashing the password."""
        if 'password' in data:
            data['password_hash'] = generate_password_hash(data.pop('password'))
        
        data['organization_id'] = org_id
        return self.create(data, commit=commit)

    def get_by_email(self, email: str, org_id: int) -> Optional[OrganizationUser]:
        repository: OrganizationUserRepository = self.repository
        return repository.get_by_email_and_org(email, org_id)

    def authenticate(self, email: str, password: str, org_id: int) -> Optional[OrganizationUser]:
        user = self.get_by_email(email, org_id)
        if user and user.check_password(password):
            return user
        return None
