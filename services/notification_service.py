from models import db
from models.models import PlatformNotification

def create_notification(org_id, type, title, message, link=None):
    """
    Creates a new platform notification.
    """
    try:
        n = PlatformNotification(
            organization_id=org_id,
            type=type,
            title=title,
            message=message,
            link=link
        )
        db.session.add(n)
        db.session.commit()
        return True
    except Exception as e:
        print(f"Error creating notification: {e}")
        return False

def get_unread_count():
    return PlatformNotification.query.filter_by(is_read=False).count()

def get_recent_notifications(limit=20):
    return PlatformNotification.query.order_by(PlatformNotification.created_at.desc()).limit(limit).all()
