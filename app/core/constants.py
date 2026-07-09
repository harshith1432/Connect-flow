# System-wide constants, status codes, and error categories

# Pagination defaults
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# Subscription statuses
SUB_STATUS_ACTIVE = "active"
SUB_STATUS_INACTIVE = "inactive"
SUB_STATUS_CANCELED = "canceled"

# Subscription Plan Limits and Features Configuration
# Keys are normalized (lowercase plan name)
PLAN_LIMITS = {
    "free trial": {
        "workers": 5,
        "messages": 1000,
        "modules": 2,
        "campaigns": 3,
        "whatsapp": False,
        "custom_keys": False,
    },
    "growth": {
        "workers": 15,
        "messages": 15000,
        "modules": 5,
        "campaigns": 15,
        "whatsapp": True,
        "custom_keys": False,
    },
    "professional": {
        "workers": 50,
        "messages": 75000,
        "modules": 9999,
        "campaigns": 50,
        "whatsapp": True,
        "custom_keys": True,
    },
    "enterprise": {
        "workers": 9999,
        "messages": 9999999,
        "modules": 9999,
        "campaigns": 9999,
        "whatsapp": True,
        "custom_keys": True,
    }
}

# Campaign execution types and states
CAMPAIGN_STATUS_DRAFT = "draft"
CAMPAIGN_STATUS_RUNNING = "running"
CAMPAIGN_STATUS_COMPLETED = "completed"
CAMPAIGN_STATUS_PAUSED = "paused"
CAMPAIGN_STATUS_FAILED = "failed"

# Call/Message status types
CALL_STATUS_PENDING = "pending"
CALL_STATUS_COMPLETED = "completed"
CALL_STATUS_FAILED = "failed"
CALL_STATUS_ANSWERED = "answered"
CALL_STATUS_NO_ANSWER = "no-answer"
CALL_STATUS_BUSY = "busy"

