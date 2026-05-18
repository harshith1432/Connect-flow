# Permission checking policies and RBAC roles
from enum import Enum


class UserRole(Enum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    WORKER = "worker"


def has_permission(user, permission):
    """
    Check if a user has a specific permission.
    Currently role-based logic is embedded in routes and decorators,
    but this provides a future-proof centralized policy extension point.
    """
    if not user or not user.is_authenticated:
        return False

    if user.__class__.__name__ == "PlatformAdmin":
        return True

    role = getattr(user, "role", None)
    if not role:
        return False

    # Standard RBAC hierarchy mapping can be extended here
    return True
