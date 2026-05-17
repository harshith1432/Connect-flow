import os
import threading
import logging
from twilio.rest import Client
from flask import current_app
from models import db
from models.models import DeliveryLog, CommunicationNumber, Contact, Organization
from config import Config

logger = logging.getLogger(__name__)

# Default Global Client (fallback)
default_client = None
if Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN:
    try:
        default_client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
    except Exception as e:
        logger.exception("Failed to initialize default Twilio Client: %s", e)
else:
    logger.warning(
        "Default Twilio credentials not found; features disabled unless custom config used"
    )


def _get_twilio_context(organization_id, channel="whatsapp", sender_number_id=None):
    """
    Returns (client, sender_number) based on organization config or defaults.
    Preference:
    1. Specific Number Record (if sender_number_id is provided)
    2. Organization Custom Config (twilio_config)
    3. Platform Default Env Vars
    """
    org = db.session.get(Organization, organization_id)
    custom_conf = org.twilio_config if org else None

    client_instance = None
    sender_number = None

    # 1. Handle Specific Number Selection if provided
    if sender_number_id:
        sender_record = db.session.get(CommunicationNumber, sender_number_id)
        if (
            sender_record
            and sender_record.organization_id == organization_id
            and sender_record.active
        ):
            if sender_record.is_platform_owned:
                print(
                    f"DEBUG: Using Platform Default for number {sender_record.number}"
                )
                client_instance = default_client
                sender_number = sender_record.number
                return client_instance, sender_number
            else:
                print(
                    f"DEBUG: Using Custom DB Config for number {sender_record.number}"
                )
                if custom_conf:
                    config_key = (
                        "voice"
                        if sender_record.channel_type in ["voice", "hooman_voice"]
                        else "whatsapp"
                    )
                    channel_conf = custom_conf.get(config_key, {})
                    sid = channel_conf.get("sid")
                    token = channel_conf.get("token")
                    if sid and token:
                        client_instance = Client(sid, token)
                        sender_number = sender_record.number
                        return client_instance, sender_number

    # 2. Check Custom Config Fallback
    if not client_instance and custom_conf:
        config_key = "voice" if channel == "call" else "whatsapp"
        channel_conf = custom_conf.get(config_key, {})
        sid = channel_conf.get("sid")
        token = channel_conf.get("token")
        number = channel_conf.get("number")

        if sid and token and number:
            active_record = CommunicationNumber.query.filter_by(
                organization_id=organization_id,
                number=number,
                active=True,
                approved=True,
            ).first()

            if active_record:
                try:
                    client_instance = Client(sid, token)
                    sender_number = number
                except Exception as e:
                    logger.error(f"Failed to init custom Twilio client: {e}")

    # Fallback to Default
    if not client_instance:
        if org:
            # Check granular permissions
            allowed = True
            if channel == "call":
                allowed = org.allow_default_voice
            else:
                allowed = org.allow_default_whatsapp

            if not allowed:
                logger.info(
                    f"Org {organization_id} has disabled platform default {channel} access. Blocking fallback."
                )
                return None, None

        client_instance = default_client
        if channel == "call":
            sender_number = Config.TWILIO_VOICE_NUMBER
        else:
            sender_number = Config.TWILIO_WHATSAPP_NUMBER

    return client_instance, sender_number


def send_whatsapp_text(
    organization_id,
    contact_id,
    body=None,
    campaign_id=None,
    content_sid=None,
    content_variables=None,
    sender_number_id=None,
):
    """
    Send a WhatsApp message using Twilio. Supports raw body or Content API templates.
    """
    # 1. Log Initial Status
    log = DeliveryLog(
        organization_id=organization_id,
        campaign_id=campaign_id,
        contact_id=contact_id,
        channel="whatsapp",
        status="queued",
    )
    db.session.add(log)
    db.session.commit()

    # 2. Get Client & Sender
    client, sender_number = _get_twilio_context(
        organization_id, channel="whatsapp", sender_number_id=sender_number_id
    )

    if not client:
        log.status = "failed"
        log.error = "Twilio client not configured (Global or Custom)"
        db.session.commit()
        return log

    app = current_app._get_current_object()
    log_id = log.id

    def _send():
        with app.app_context():
            # Re-fetch within thread's context/session
            thread_log = db.session.get(DeliveryLog, log_id)
            thread_contact = db.session.get(Contact, contact_id)

            try:
                if not thread_contact:
                    raise ValueError(
                        f"Contact {contact_id} not found in background thread"
                    )

                import re

                to_num = re.sub(r"\D", "", thread_contact.phone)
                if len(to_num) == 10:
                    to_num = "91" + to_num
                if not to_num.startswith("+"):
                    to_num = "+" + to_num
                to = f"whatsapp:{to_num}"

                # Ensure sender has whatsapp: prefix
                from_ = (
                    sender_number
                    if sender_number and sender_number.startswith("whatsapp:")
                    else f"whatsapp:{sender_number}"
                )

                # Status Callback URL
                callback_url = (
                    f"{Config.BASE_URL.rstrip('/')}/api/twilio/message-status"
                )
                print(f"[DEBUG DISPATCH] Using Callback URL: {callback_url}")

                kwargs = {"from_": from_, "to": to, "status_callback": callback_url}

                if content_sid:
                    kwargs["content_sid"] = content_sid
                    if content_variables:
                        kwargs["content_variables"] = content_variables
                else:
                    kwargs["body"] = body or ""

                logger.info(
                    "Twilio send request: %s (Org: %s)", kwargs, organization_id
                )
                msg = client.messages.create(**kwargs)
                print(
                    f"[DEBUG DISPATCH] Message Created! SID: {msg.sid}, Status: {msg.status}"
                )

                if thread_log:
                    thread_log.sid = msg.sid
                    thread_log.recipient = to_num
                    thread_log.status = msg.status
                    thread_log.meta = {"twilio_sid": msg.sid}
                    db.session.commit()
                    print(f"[DEBUG DISPATCH] Log updated in DB for ID: {thread_log.id}")
                logger.info("Sent WhatsApp to %s, SID: %s", to, msg.sid)
            except Exception as e:
                if thread_log:
                    thread_log.status = "failed"
                    thread_log.error = str(e)
                logger.error("Failed sending WhatsApp to contact %s: %s", contact_id, e)
            finally:
                db.session.commit()

    threading.Thread(target=_send, daemon=True).start()
    return log


def make_call(
    organization_id,
    contact_id,
    tts_text,
    language="English",
    campaign_id=None,
    sender_number_id=None,
):
    """
    Initiate a voice call via Twilio.
    """
    import traceback

    logger.info("make_call invoked for Org %s, Contact %s", organization_id, contact_id)
    print(
        f"DEBUG: make_call initiated for Org {organization_id}, Contact {contact_id}, Sender {sender_number_id}"
    )

    log = DeliveryLog(
        organization_id=organization_id,
        campaign_id=campaign_id,
        contact_id=contact_id,
        channel="call",
        status="queued",
    )
    db.session.add(log)
    db.session.commit()

    client, sender_number = _get_twilio_context(
        organization_id, channel="call", sender_number_id=sender_number_id
    )

    if not client:
        print(f"DEBUG: Twilio client NOT configured for Org {organization_id}")
        log.status = "failed"
        log.error = "Twilio client not configured"
        db.session.commit()
        return log

    app = current_app._get_current_object()
    log_id = log.id

    def _call():
        with app.app_context():
            thread_log = db.session.get(DeliveryLog, log_id)
            thread_contact = db.session.get(Contact, contact_id)
            try:
                if not thread_contact:
                    raise ValueError(
                        f"Contact {contact_id} not found in background thread"
                    )

                import re

                from_raw = sender_number
                print(f"DEBUG: Twilio using sender number: {from_raw}")
                if from_raw and from_raw.startswith("whatsapp:"):
                    from_raw = from_raw.replace("whatsapp:", "")

                # Normalization
                to_num = re.sub(r"\D", "", thread_contact.phone)
                if len(to_num) == 10:
                    to_num = "91" + to_num
                if not to_num.startswith("+"):
                    to_num = "+" + to_num

                # Language Mapping
                TWILIO_LANGUAGE_MAP = {
                    "English": "en-IN",
                    "Hindi": "hi-IN",
                    "Tamil": "ta-IN",
                    "Telugu": "te-IN",
                    "Kannada": "kn-IN",
                    "Malayalam": "ml-IN",
                    "Gujarati": "gu-IN",
                    "Marathi": "mr-IN",
                    "Punjabi": "pa-IN",
                    "Bengali": "bn-IN",
                    "Odia": "or-IN",
                }
                twilio_lang = TWILIO_LANGUAGE_MAP.get(language, "en-IN")

                callback_url = f"{Config.BASE_URL.rstrip('/')}/api/twilio/voice-status"
                print(f"[DEBUG CALL] Using Callback URL: {callback_url}")

                logger.info(
                    "Twilio initiating call: to=%s, from=%s, lang=%s",
                    to_num,
                    from_raw,
                    twilio_lang,
                )
                print(
                    f"DEBUG: Twilio calling {to_num} from {from_raw} with Text: {tts_text[:50]}..."
                )

                call = client.calls.create(
                    twiml=f'<Response><Say language="{twilio_lang}">{tts_text}</Say></Response>',
                    to=to_num,
                    from_=from_raw,
                    status_callback=callback_url,
                    status_callback_method="POST",
                    status_callback_event=[
                        "initiated",
                        "ringing",
                        "answered",
                        "completed",
                    ],
                )
                print(
                    f"[DEBUG CALL] Call Created! SID: {call.sid}, Status: {call.status}"
                )
                if thread_log:
                    thread_log.sid = call.sid
                    thread_log.recipient = to_num
                    thread_log.status = call.status
                    thread_log.meta = {"twilio_sid": call.sid}
                    db.session.commit()
                    print(f"[DEBUG CALL] Log updated in DB for ID: {thread_log.id}")
            except Exception as e:
                log_error = str(e)
                print(f"DEBUG: Twilio Call FAILED: {log_error}")
                if thread_log:
                    thread_log.status = "failed"
                    thread_log.error = log_error
                logger.error("Failed initiating call to contact %s: %s", contact_id, e)
            finally:
                db.session.commit()

    threading.Thread(target=_call, daemon=True).start()
    return log
