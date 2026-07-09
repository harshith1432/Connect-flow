import os
import threading
import logging
import re
from twilio.rest import Client
from flask import current_app
from app.extensions import db
from app.models import DeliveryLog, CommunicationNumber, Contact, Organization
from app.config import Config

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


def resolve_whatsapp_sender(organization_id):
    """
    Resolve a WhatsApp-only sender for the given org.

    Priority:
      1. Org custom twilio_config → whatsapp → number
      2. ENV: TWILIO_WHATSAPP_FROM / TWILIO_WHATSAPP_NUMBER
      3. Raise ValueError — do NOT silently fall through to a voice number.

    Always returns (client, sender_str) where sender_str starts with 'whatsapp:'.
    Raises ValueError if no sender can be resolved.
    """
    org = db.session.get(Organization, organization_id)
    custom_conf = org.twilio_config if org else None

    client_instance = None
    sender_number   = None

    # 1. Org custom whatsapp config
    if custom_conf:
        wa_conf = custom_conf.get("whatsapp", {})
        sid    = wa_conf.get("sid")
        token  = wa_conf.get("token")
        number = wa_conf.get("number")

        if sid and token and number:
            # Verify the number is active & approved
            active_record = CommunicationNumber.query.filter_by(
                organization_id=organization_id,
                number=number,
                active=True,
                approved=True,
            ).first()
            if active_record:
                try:
                    client_instance = Client(sid, token)
                    sender_number   = number
                    logger.info(
                        "[SENDER RESOLVED] org=%s custom whatsapp=%s",
                        organization_id, number
                    )
                except Exception as e:
                    logger.error("[SENDER RESOLVE] Custom client init failed: %s", e)

    # 2. Platform default (env)
    if not client_instance:
        if org and not org.allow_default_whatsapp:
            raise ValueError(
                f"Org {organization_id} has disabled platform WhatsApp access. "
                "Configure a custom WhatsApp sender or enable platform default."
            )
        if not default_client:
            raise ValueError(
                "Platform Twilio client not initialised — check TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN"
            )
        fallback_number = Config.TWILIO_WHATSAPP_NUMBER
        if not fallback_number:
            raise ValueError(
                "TWILIO_WHATSAPP_FROM / TWILIO_WHATSAPP_NUMBER not set in environment."
            )
        client_instance = default_client
        sender_number   = fallback_number
        logger.info(
            "[SENDER RESOLVED] org=%s using platform default=%s",
            organization_id, sender_number
        )

    # Normalise to whatsapp: prefix
    if not sender_number.startswith("whatsapp:"):
        sender_number = f"whatsapp:{sender_number}"

    return client_instance, sender_number


def _validate_audio_url(url: str) -> tuple:
    """
    Pre-flight check before handing an audio URL to Twilio.

    Verifies:
      - URL returns HTTP 200
      - Content-Type contains 'audio'
      - File is under the 16 MB Twilio media limit

    Returns (True, None) on pass, (False, reason) on fail.
    BASE_URL is read from the .env file via Config.BASE_URL.
    """
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "CampaignVoiceValidation/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status       = resp.status
            content_type = resp.headers.get("Content-Type", "")
            content_len  = resp.headers.get("Content-Length", "0")

            if status != 200:
                return False, f"HTTP {status} (expected 200)"

            if "audio" not in content_type.lower():
                return False, (
                    f"Content-Type '{content_type}' is not audio — "
                    "Ensure the server returns Content-Type: audio/mpeg for .mp3 files."
                )

            try:
                size_mb = int(content_len) / (1024 * 1024)
                if size_mb > 16:
                    return False, f"File is {size_mb:.1f} MB — exceeds Twilio 16 MB limit"
            except (ValueError, TypeError):
                pass  # Content-Length absent — let Twilio decide

            return True, None

    except Exception as exc:
        return False, f"URL unreachable ({type(exc).__name__}): {exc}"


def send_whatsapp_text(
    organization_id,
    contact_id=None,
    body=None,
    campaign_id=None,
    content_sid=None,
    content_variables=None,
    sender_number_id=None,
    to_number=None,
    record_id=None,
):
    """
    Send a WhatsApp TEXT message via Twilio (synchronous).

    Returns (success: bool, sid: str | None, error: str | None).

    Priority for sender:
      1. sender_number_id  → CommunicationNumber record
      2. org custom twilio_config → whatsapp number
      3. TWILIO_WHATSAPP_FROM env  (Config.TWILIO_WHATSAPP_NUMBER)
      4. ERROR — do NOT silently block

    Only client.messages.create() is called — no voice, no TwiML.
    """
    from app.core.logging_system import log_activity

    log_activity("WHATSAPP_START",
                 f"org={organization_id} to={to_number} campaign={campaign_id}")

    # ── 1. Resolve phone ──────────────────────────────────────────
    phone_str = to_number
    if contact_id and not phone_str:
        contact = db.session.get(Contact, contact_id)
        if contact:
            phone_str = contact.phone

    if not phone_str:
        err = f"No recipient phone for contact_id={contact_id}"
        logger.error("[WHATSAPP FAILED] %s", err)
        log_activity("WHATSAPP_FAILED", err)
        return False, None, err

    to_num = re.sub(r"\D", "", phone_str)
    if len(to_num) == 10:
        to_num = "91" + to_num
    if not to_num.startswith("+"):
        to_num = "+" + to_num
    to = f"whatsapp:{to_num}"

    # ── 2. Resolve client & sender ────────────────────────────────
    client, sender_number = _get_twilio_context(
        organization_id, channel="whatsapp", sender_number_id=sender_number_id
    )

    if not client or not sender_number:
        err = (
            "WhatsApp sender not configured — "
            "set a WhatsApp number for this organization or enable platform default access."
        )
        logger.error("[WHATSAPP FAILED] org=%s  %s", organization_id, err)
        log_activity("WHATSAPP_FAILED", f"org={organization_id} — {err}")
        return False, None, err

    from_ = (
        sender_number
        if sender_number.startswith("whatsapp:")
        else f"whatsapp:{sender_number}"
    )
    log_activity("SENDER_VALIDATED", f"from={from_} to={to}")

    # ── 3. Build request kwargs ───────────────────────────────────
    callback_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/twilio/message-status"
    kwargs = {"from_": from_, "to": to, "status_callback": callback_url}

    if content_sid:
        kwargs["content_sid"] = content_sid
        if content_variables:
            kwargs["content_variables"] = content_variables
    else:
        kwargs["body"] = body or ""

    log_activity("TWILIO_REQUEST",
                 f"from={from_} to={to} content_sid={content_sid}")
    logger.info("Twilio send request: %s (Org: %s)", kwargs, organization_id)

    # ── 4. Send — ONLY messages.create(), no calls ────────────────
    try:
        msg = client.messages.create(**kwargs)
    except Exception as exc:
        err = str(exc)
        logger.error("[WHATSAPP FAILED] Twilio exception: %s", err)
        log_activity("WHATSAPP_FAILED", f"TwilioException: {err}")
        return False, None, err

    # ── 5. Evaluate result ────────────────────────────────────────
    FAILURE_STATUSES = {"failed", "undelivered"}
    if not msg.sid or msg.status in FAILURE_STATUSES:
        err = f"Twilio returned sid={msg.sid} status={msg.status}"
        logger.error("[WHATSAPP FAILED] %s", err)
        log_activity("WHATSAPP_FAILED", err)
        return False, msg.sid, err

    logger.info("[TWILIO_SID] sid=%s status=%s to=%s", msg.sid, msg.status, to)
    log_activity("TWILIO_SID", f"sid={msg.sid} status={msg.status} to={to}")

    # ── 6. Write DeliveryLog (optional — campaign_runner may have its own) ──
    try:
        log = DeliveryLog(
            organization_id=organization_id,
            campaign_id=campaign_id,
            contact_id=contact_id,
            record_id=record_id,
            channel="whatsapp",
            recipient=to_num,
            status=msg.status,
            sid=msg.sid,
            meta={"twilio_sid": msg.sid, "from": from_},
        )
        db.session.add(log)
        db.session.commit()
    except Exception as db_exc:
        logger.warning("[WHATSAPP] DeliveryLog write failed: %s", db_exc)

    log_activity("DELIVERED", f"sid={msg.sid} to={to}")
    return True, msg.sid, None


def send_whatsapp_bundle(
    organization_id,
    to_number,
    body,
    campaign_id,
    target_id,
    language="English",
    gender="female",
    content_sid=None,
    content_variables=None,
    record_id=None,
    sender_number_id=None,
):
    """
    Send WhatsApp TEXT + WhatsApp VOICE NOTE as two separate messages.

    Steps:
      1. Send text  via messages.create(body=...)
      2. Generate MP3 via audio_generator.generate_voice_note()
      3. Upload / serve MP3 and send via messages.create(media_url=[...])

    Returns:
      (text_success, text_sid, audio_success, audio_sid, error)

    Both messages are sent even if one fails so that the campaign runner
    can decide the final status (completed / partial_success / failed).

    IMPORTANT: Only client.messages.create() is used — no calls/TwiML.
    """
    from app.core.logging_system import log_activity
    from app.services.audio_generator import generate_voice_note
    from app.config import Config

    log_activity("BUNDLE_START", f"campaign={campaign_id} target={target_id} to={to_number}")

    # ── 1. Resolve client & sender ────────────────────────────────────────────
    client, sender_number = _get_twilio_context(
        organization_id, channel="whatsapp", sender_number_id=sender_number_id
    )
    if not client or not sender_number:
        err = (
            "WhatsApp sender not configured — "
            "set a WhatsApp number for this organization or enable platform default access."
        )
        logger.error("[BUNDLE FAILED] org=%s  %s", organization_id, err)
        return False, None, False, None, err

    # Normalise phone
    to_num = re.sub(r"\D", "", to_number)
    if len(to_num) == 10:
        to_num = "91" + to_num
    if not to_num.startswith("+"):
        to_num = "+" + to_num
    to = f"whatsapp:{to_num}"

    from_ = (
        sender_number
        if sender_number.startswith("whatsapp:")
        else f"whatsapp:{sender_number}"
    )
    callback_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/twilio/message-status"

    # ── 2. Send TEXT ──────────────────────────────────────────────────────────
    text_success = False
    text_sid     = None
    text_error   = None

    logger.info("[WHATSAPP TEXT] sending to %s", to)
    log_activity("WHATSAPP_TEXT", f"to={to}")

    try:
        text_kwargs = {"from_": from_, "to": to, "status_callback": callback_url}
        if content_sid:
            text_kwargs["content_sid"] = content_sid
            if content_variables:
                text_kwargs["content_variables"] = content_variables
        else:
            text_kwargs["body"] = body or ""

        text_msg    = client.messages.create(**text_kwargs)
        text_sid    = text_msg.sid
        text_success = bool(text_sid) and text_msg.status not in {"failed", "undelivered"}
        logger.info("[TEXT SENT] sid=%s status=%s", text_sid, text_msg.status)
        log_activity("WHATSAPP_TEXT_SID", f"sid={text_sid} status={text_msg.status}")
    except Exception as exc:
        text_error = str(exc)
        logger.error("[WHATSAPP TEXT FAILED] %s", text_error)
        log_activity("WHATSAPP_TEXT_FAILED", text_error)

    # ── 3. Generate audio ─────────────────────────────────────────────────────
    audio_success = False
    audio_sid     = None
    audio_error   = None

    speak_text = body or ""
    logger.info("[AUDIO GENERATING] target=%s lang=%s", target_id, language)

    audio_path = generate_voice_note(
        text=speak_text,
        campaign_id=campaign_id,
        target_id=target_id,
        language=language,
        gender=gender,
    )

    if not audio_path:
        audio_error = "TTS generation failed — no audio file produced"
        logger.error("[AUDIO FAILED] target=%s", target_id)
        log_activity("AUDIO_FAILED", f"target={target_id}")
        return text_success, text_sid, False, None, audio_error or text_error

    log_activity("AUDIO GENERATED", f"path={audio_path}")

    # ── 4. Build public URL for the MP3 attachment ────────────────────────────
    #    URL uses BASE_URL from .env — must be publicly reachable by Twilio.
    filename  = os.path.basename(audio_path)   # campaign_<id>_target_<id>.mp3
    audio_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/static/audio/voice_notes/{filename}"
    logger.info("[AUDIO URL] %s", audio_url)
    log_activity("AUDIO URL", f"url={audio_url}")

    # ── 5. Validate URL before sending to Twilio ──────────────────────────────
    url_ok, url_err = _validate_audio_url(audio_url)
    if not url_ok:
        audio_error = f"Audio URL validation failed: {url_err}"
        logger.error("[VOICE FAILED] %s", audio_error)
        log_activity("VOICE_FAILED", audio_error)
        final_error = audio_error or text_error
        log_activity(
            "BUNDLE_DONE",
            f"text_ok={text_success}({text_sid}) audio_ok=False (url_invalid)"
        )
        return text_success, text_sid, False, None, final_error

    logger.info("[MP3 SENT] Sending MP3 media_url=%s", audio_url)
    log_activity("MP3 SENT", f"url={audio_url}")

    # ── 6. Send AUDIO as WhatsApp media attachment ────────────────────────────
    try:
        audio_msg     = client.messages.create(
            from_=from_,
            to=to,
            body="🎤 Audio Message",
            media_url=[audio_url],
            status_callback=callback_url,
        )
        audio_sid     = audio_msg.sid
        audio_success = bool(audio_sid) and audio_msg.status not in {"failed", "undelivered"}
        logger.info(
            "[DELIVERED] sid=%s status=%s url=%s",
            audio_sid, audio_msg.status, audio_url
        )
        log_activity("DELIVERED", f"sid={audio_sid} status={audio_msg.status}")
    except Exception as exc:
        audio_error = str(exc)
        logger.error("[VOICE FAILED] %s", audio_error)
        log_activity("VOICE_FAILED", audio_error)

    final_error = audio_error or text_error
    log_activity(
        "BUNDLE_DONE",
        f"text_ok={text_success}({text_sid}) audio_ok={audio_success}({audio_sid})"
    )
    return text_success, text_sid, audio_success, audio_sid, final_error


def make_call(
    organization_id,
    contact_id,
    tts_text,
    language="English",
    campaign_id=None,
    sender_number_id=None,
    phone=None,
    record_id=None,
):
    """
    Initiate a voice call via Twilio.
    """
    logger.info("make_call invoked for Org %s, Contact %s", organization_id, contact_id)
    print(
        f"DEBUG: make_call initiated for Org {organization_id}, Contact {contact_id}, Sender {sender_number_id}"
    )

    log = DeliveryLog(
        organization_id=organization_id,
        campaign_id=campaign_id,
        contact_id=contact_id,
        record_id=record_id,
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
                phone_str = phone
                if contact_id and not phone_str:
                    if not thread_contact:
                        raise ValueError(
                            f"Contact {contact_id} not found in background thread"
                        )
                    phone_str = thread_contact.phone

                if not phone_str:
                    raise ValueError("No recipient phone provided")

                from_raw = sender_number
                print(f"DEBUG: Twilio using sender number: {from_raw}")
                if from_raw and from_raw.startswith("whatsapp:"):
                    from_raw = from_raw.replace("whatsapp:", "")

                # Normalization
                to_num = re.sub(r"\D", "", phone_str)
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

                callback_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/twilio/voice-status"
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
