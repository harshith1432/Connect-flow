from app.extensions import db

# Platform configuration and owner models
from .platform import Role, PlatformAdmin, Plan, PaymentMethod, PlatformSecurity

# Organization and subscription models
from .organization import Organization, Subscription, Payment, CommunicationNumber

# Workers and contact models
from .worker import OrganizationUser, Contact, ContactGroup, ContactGroupMap

# Custom CRM forms metadata models
from .modules import Module, ModuleGroup, ModuleField, ModuleRecord, ModuleRecordValue

# Workforce templates
from .scripts import Script

# Call/SMS campaigns models
from .campaigns import Campaign, CampaignTarget, DeliveryLog, CallTargetResult

# Administrative audits and alert logs
from .change_requests import ChangeRequest, PlatformNotification

# Real-time chat and custom notification models
from .chat import ChatMessage, DashboardNotification

# Platform Helpdesk tickets model
from .helpdesk import HelpdeskQuery

# Public landing page inquiry / talk-to-us leads
from .inquiry import Inquiry

# Campaign Express standalone user and payment models
from .campaign_express import CampaignExpressUser, CampaignExpressPayment

# Campaign Express platform-owned number pool
from .ce_number_pool import CeNumberPool, CeCampaignNumberAssignment

# Security infrastructure models
from .security import (
    MfaConfiguration,
    OtpVerification,
    ActiveSession,
    SecurityAuditLog,
    SuspiciousActivity,
)

# Payment manual verification requests model
from .payment_verification import PaymentVerification
