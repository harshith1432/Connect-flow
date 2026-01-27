"""
Central WhatsApp dispatcher.

Routes WhatsApp sends to either:
 - Twilio (via services.twilio_service)
 - Custom bot HTTP API (platform's Node.js bot or `whatsapp_automation.py` helper)

This module implements a single `dispatch_whatsapp` function used across the app.
It performs:
 - organization lookup
 - channel selection (organization.whatsapp_channel_type)
 - calls the appropriate sender
 - graceful error handling and delivery log creation

Design notes:
 - We prefer an existing `whatsapp_automation` Python module if present (reused, not rewritten).
 - If not present, the dispatcher will POST to `BOT_SERVER_URL` from config (if configured).
 - Twilio sending is delegated to `services.twilio_service` which already creates DeliveryLog entries.
 - For custom bot sends we create and update DeliveryLog similarly.
"""
import threading
import logging
import requests

from models import db
from models.models import Organization, Contact, DeliveryLog
from config import Config

from services.twilio_service import send_whatsapp_text, send_whatsapp_voice

logger = logging.getLogger(__name__)

def dispatch_whatsapp(organization_id, contact_id, message=None, audio_url=None, campaign_id=None, content_sid=None, content_variables=None, local_path=None, sender_number_id=None):
    """
    Dispatch a WhatsApp message for an organization using Twilio.
    """
    org = Organization.query.get(organization_id)
    if not org:
        logger.error('dispatch_whatsapp: organization not found %s', organization_id)
        raise ValueError('organization not found')

    contact = Contact.query.get(contact_id)
    if not contact:
        logger.error('dispatch_whatsapp: contact not found %s', contact_id)
        raise ValueError('contact not found')

    # All WhatsApp delivery is now via Twilio
    if audio_url:
        return send_whatsapp_voice(organization_id, contact_id, audio_url=audio_url, campaign_id=campaign_id, local_path=local_path, sender_number_id=sender_number_id)
    else:
        return send_whatsapp_text(
            organization_id, 
            contact_id, 
            body=message or '', 
            campaign_id=campaign_id,
            content_sid=content_sid,
            content_variables=content_variables,
            sender_number_id=sender_number_id
        )
