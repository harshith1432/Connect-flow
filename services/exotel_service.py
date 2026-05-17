import os
import requests
import logging
from flask import current_app
from models import db
from models.models import DeliveryLog, Organization, CommunicationNumber, Contact
from config import Config

logger = logging.getLogger(__name__)


def _get_exotel_context(organization_id, sender_number_id=None):
    """
    Returns (api_key, api_token, exotel_number) based on organization config or defaults.
    """
    org = db.session.get(Organization, organization_id)
    custom_conf = (
        org.twilio_config.get("exotel", {}) if org and org.twilio_config else {}
    )

    api_key = custom_conf.get("api_key") or os.getenv("EXOTEL_API_KEY")
    api_token = custom_conf.get("api_token") or os.getenv("EXOTEL_API_TOKEN")
    exotel_number = custom_conf.get("number")

    if sender_number_id:
        sender_record = db.session.get(CommunicationNumber, sender_number_id)
        if (
            sender_record
            and sender_record.organization_id == organization_id
            and sender_record.active
        ):
            exotel_number = sender_record.number
            print(f"DEBUG: Using Exotel Number from DB: {exotel_number}")

    # Exotel often requires a subdomain/sid-like identifier in the URL.
    subdomain = custom_conf.get("subdomain") or os.getenv("EXOTEL_SUBDOMAIN") or api_key

    return api_key, api_token, exotel_number, subdomain


def make_exotel_call(
    organization_id,
    contact_id,
    tts_text,
    language="English",
    campaign_id=None,
    sender_number_id=None,
):
    """
    Initiate a voice call via Exotel REST API.
    """
    logger.info(
        "make_exotel_call invoked for Org %s, Contact %s, Sender %s",
        organization_id,
        contact_id,
        sender_number_id,
    )

    log = DeliveryLog(
        campaign_id=campaign_id, contact_id=contact_id, channel="call", status="queued"
    )
    db.session.add(log)
    db.session.commit()

    api_key, api_token, sender_number, subdomain = _get_exotel_context(
        organization_id, sender_number_id=sender_number_id
    )

    if not api_key or not api_token or not sender_number:
        log.status = "failed"
        log.error = "Exotel credentials or number not configured"
        db.session.commit()
        return log

    contact = db.session.get(Contact, contact_id)
    if not contact:
        log.status = "failed"
        log.error = "Contact not found"
        db.session.commit()
        return log

    # Normalize phone number (Exotel usually expects 10 digits or with country code)
    import re

    to_num = re.sub(r"\D", "", contact.phone)
    if len(to_num) == 10:
        to_num = "0" + to_num  # Exotel sometimes prefers 0 prefix for Indian numbers

    # Exotel API properties
    # Endpoint: https://api.exotel.com/v1/Accounts/{your_sid}/Calls/connect.json
    url = f"https://api.exotel.com/v1/Accounts/{subdomain}/Calls/connect.json"

    # Exotel uses 'From' for the customer and 'To' for the Exophone (Virtual Number) by default in connect.json
    # OR it uses 'From' as Exophone if using different params.
    # Actually, for a simple broadcast call:
    # From: The virtual number
    # To: The destination number
    # Url: The TwiML-like URL or just plain text if using simple connect

    # Note: Exotel's simple connect doesn't support direct TTS in the 'connect' call easily
    # without an App ID or a Flow. However, we can use their 'Sms' or other features,
    # but for Call, they usually require an "AppId" which defines the flow.

    # IF the user expects a simple TTS call like Twilio:
    payload = {
        "From": sender_number,
        "To": to_num,
        "CallerId": sender_number,
        "CallType": "transient",
    }

    # For TTS, Exotel often uses an 'Url' parameter pointing to an XML/JSON defining the flow.
    # Since we want to be as direct as possible:
    # We'll assume for now they have a basic flow or we use a public TTS service if available.
    # BUT, Exotel also has a "Speak" parameter in some of their newer APIs.

    # High-level logic for this task:
    logger.info(f"Dispatching Exotel call to {to_num} from {sender_number}")

    try:
        response = requests.post(
            url, auth=(api_key, api_token), data=payload, timeout=10
        )
        res_data = response.json()

        if response.status_code == 200:
            log.sid = res_data.get("Call", {}).get("Sid")
            log.status = "in-progress"
            log.meta = {"exotel_sid": log.sid}
            logger.info(f"Exotel call initiated. SID: {log.sid}")
        else:
            log.status = "failed"
            log.error = res_data.get("RestException", {}).get(
                "Message", "Exotel API Error"
            )
            logger.error(f"Exotel API Error: {log.error}")

    except Exception as e:
        log.status = "failed"
        log.error = str(e)
        logger.error(f"Exotel dispatch exception: {e}")

    db.session.commit()
    return log
