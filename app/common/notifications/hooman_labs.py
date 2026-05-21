"""
hooman_labs_service.py
----------------------
Production-ready integration with the Hooman Labs voice API.

Features:
- Validates BASE_URL is set and not localhost before any API call
- Full structured logging at every step
- Async dispatch via background thread (non-blocking)
- Delivery log created immediately; status updated asynchronously
- Graceful fallback error handling with log.error details
"""

import json
import logging
import threading
import time
import requests
from datetime import datetime, timedelta
import pytz

from app.extensions import db
from app.models import Contact, DeliveryLog, Organization, CommunicationNumber
from flask import current_app

logger = logging.getLogger(__name__)

# Hooman Labs API endpoint
HOOMAN_TASKS_URL = "https://api.hoomanlabs.com/routes/v1/tasks/"


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _get_base_url(app) -> str:
    """
    Load and validate BASE_URL from Flask app config.
    Must be a non-empty, non-localhost public URL.
    """
    base_url = app.config.get("PUBLIC_BASE_URL", app.config.get("BASE_URL", "")).strip().rstrip("/")

    if not base_url:
        raise ValueError(
            "PUBLIC_BASE_URL is not configured in .env. "
            "Set it to your Cloudflare tunnel domain, e.g. "
            "PUBLIC_BASE_URL=https://usd-infectious-table-nec.trycloudflare.com"
        )

    if "localhost" in base_url or "127.0.0.1" in base_url:
        raise ValueError(
            f"PUBLIC_BASE_URL is set to a local address ({base_url}). "
            "Hooman Labs requires a publicly accessible URL."
        )

    return base_url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_hooman_call(
    organization_id: int,
    contact_id: int,
    tts_text: str,
    language: str = "English",
    campaign_id: int = None,
    sender_number_id: int = None,
):
    """
    Initiate a Hooman Labs voice call for a contact.

    Args:
        organization_id:    ID of the calling organization.
        contact_id:         ID of the contact to call.
        tts_text:           Script text (used as message body).
        language:           Language name for agent selection (e.g. "Hindi").
        campaign_id:        Campaign ID for delivery log linkage.
        sender_number_id:   Sender number config ID.

    Returns:
        DeliveryLog instance (status="pending") or None on fatal setup error.
    """
    # 1. Load and validate required records
    org = db.session.get(Organization, organization_id)
    contact = db.session.get(Contact, contact_id)

    if not org:
        logger.error(f"[HoomanLabs] Organization {organization_id} not found.")
        return None
    if not contact:
        logger.error(f"[HoomanLabs] Contact {contact_id} not found.")
        return None

    # 2. Extract Hooman Labs org config
    config = org.hooman_config or (org.twilio_config or {}).get("hooman_labs", {})
    api_key = config.get("api_key", "").strip()

    # Resolve 'from' number
    from_number = config.get("number", "").strip()

    if not from_number and sender_number_id:
        sender = db.session.get(CommunicationNumber, sender_number_id)
        if sender:
            from_number = sender.number

    # Require API Key
    if not api_key:
        logger.error(
            f"[HoomanLabs] Missing 'api_key' in hooman_config "
            f"for organization {organization_id}. Go to Org Settings → Communication Settings "
            f"and fill in the Hooman Labs section."
        )
        return None

    # 3. Resolve agent ID based on script language name
    app = current_app._get_current_object()

    # Map script language names to their config keys
    LANGUAGE_AGENT_MAP = {
        "English": "HOOMAN_AGENT_ENGLISH",
        "Hindi": "HOOMAN_AGENT_HINDI",
        "Tamil": "HOOMAN_AGENT_TAMIL",
        "Kannada": "HOOMAN_AGENT_KANNADA",
        "Telugu": "HOOMAN_AGENT_TELUGU",
        "Marathi": "HOOMAN_AGENT_MARATHI",
        "Punjabi": "HOOMAN_AGENT_PUNJABI",
        "Gujarati": "HOOMAN_AGENT_GUJARATI",
        "Malayalam": "HOOMAN_AGENT_MALAYALAM",
    }

    config_key = LANGUAGE_AGENT_MAP.get(language)
    agent_id = ""
    if config_key:
        agent_id = app.config.get(config_key, "")

    # Fallback to generic voice call agent if no language-specific agent found
    if not agent_id:
        agent_id = app.config.get("HOOMAN_AGENT_VOICE_CALL", "")

    if not agent_id:
        logger.warning(
            f"[HoomanLabs] No agent ID found for language '{language}'. "
            f"Using empty string - call may fail."
        )

    logger.info(
        f"[HoomanLabs] Dispatching call → contact={contact.phone}, "
        f"language={language}, agent={agent_id}"
    )

    # 5. Create delivery log (status=pending, committed before thread starts)
    log = DeliveryLog(
        organization_id=organization_id,
        contact_id=contact_id,
        campaign_id=campaign_id,
        channel="hooman_voice",
        recipient=contact.phone,
        status="pending",
        meta={
            "language": language,
        },
    )
    db.session.add(log)
    db.session.commit()
    log_id = log.id

    # 6. Dispatch in background thread (non-blocking)
    def _dispatch():
        logger.info(" Dispatching call immediately to Hooman Labs")

        with app.app_context():
            thread_log = db.session.get(DeliveryLog, log_id)
            thread_contact = db.session.get(Contact, contact_id)

            if not thread_log or not thread_contact:
                logger.error(
                    f"[HoomanLabs] Thread: DeliveryLog {log_id} or Contact {contact_id} "
                    f"disappeared before dispatch."
                )
                return

            try:
                try:
                    _base = _get_base_url(app)
                    status_callback_url = f"{_base}/webhook"
                except ValueError:
                    status_callback_url = None
                    logger.warning(
                        "[HoomanLabs] PUBLIC_BASE_URL not available — "
                        "status_callback_url will not be sent."
                    )

                logger.info(
                    f"!!! [SCHEDULER] Dispatching call at {datetime.now().strftime('%H:%M')} !!!"
                )

                india = pytz.timezone("Asia/Kolkata")
                now = datetime.now(india)

                start_after = now + timedelta(minutes=1)
                end_after = now + timedelta(hours=24)
                payload = {
                    "campaign": str(app.config.get("HOOMAN_CAMPAIGN_ID", "")),
                    "company": "default",
                    "agent": str(agent_id) if agent_id else "",
                    "phone": str(thread_contact.phone) if thread_contact.phone else "",
                    "from": str(from_number) if from_number else "",
                    "start": 0000,  # start after 1 mins
                    "end": 4759,  # valid for 24 hrs
                    "timezone": "Asia/Kolkata",
                    "startAfter": start_after.isoformat(),
                    "endAfter": end_after.isoformat(),
                    "priority": [1],
                    "retries": 1,
                    "intervals": [120],  # Retry after 120 seconds
                    "context": {
                        "message": str(tts_text) if tts_text else "",
                    },
                }

                logger.info(
                    f"[HoomanLabs] Payload built — message length={len(tts_text) if tts_text else 0}"
                )

                if status_callback_url:
                    payload["statusCallbackUrl"] = str(status_callback_url)
                    logger.info(f"[HoomanLabs] Status callback → {status_callback_url}")

                headers = {
                    "Authorization": f"Bearer {str(api_key)}",
                    "Content-Type": "application/json",
                }

                hooman_org_id = app.config.get("HOOMAN_ORGANIZATION_ID")
                if hooman_org_id:
                    headers["X-Hooman-Organization"] = str(hooman_org_id)
                    logger.info(f"[HoomanLabs] Using Org ID: {hooman_org_id}")

                try:
                    p_log = json.dumps(payload, ensure_ascii=False)
                except Exception:
                    p_log = str(payload)

                logger.debug(f"[HoomanLabs] POST {HOOMAN_TASKS_URL} | payload={p_log}")

                response = requests.post(
                    HOOMAN_TASKS_URL,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )

                response_text = response.text
                logger.info(
                    f"[HoomanLabs] API response: status={response.status_code}, "
                    f"body={response_text[:300]}"
                )

                if response.status_code in (200, 201, 202):
                    thread_log.status = "initiated"
                    try:
                        resp_json = response.json()
                        thread_log.sid = str(
                            resp_json.get("taskId")
                            or resp_json.get("task_id")
                            or resp_json.get("task")
                            or resp_json.get("id")
                            or ""
                        )
                        logger.info(
                            f"[HoomanLabs] Task created successfully. "
                            f"sid={thread_log.sid}, contact={thread_contact.phone}"
                        )
                    except Exception:
                        pass
                else:
                    logger.error(
                        f"[HoomanLabs] API call failed: "
                        f"HTTP {response.status_code} → {response_text}"
                    )
                    thread_log.status = "failed"
                    thread_log.error = f"HTTP {response.status_code}: {response_text}"

            except requests.exceptions.Timeout:
                logger.error(
                    f"[HoomanLabs] Request timed out for contact {contact_id}."
                )
                thread_log.status = "failed"
                thread_log.error = "Request timed out after 30 seconds."

            except requests.exceptions.ConnectionError as e:
                logger.error(f"[HoomanLabs] Connection error: {e}")
                thread_log.status = "failed"
                thread_log.error = f"Connection error: {e}"

            except Exception as e:
                logger.exception(f"[HoomanLabs] Unexpected error during dispatch: {e}")
                thread_log.status = "failed"
                thread_log.error = str(e)

            finally:
                try:
                    db.session.commit()
                except Exception as commit_err:
                    logger.error(
                        f"[HoomanLabs] DB commit failed after dispatch: {commit_err}"
                    )

    threading.Thread(target=_dispatch, daemon=True).start()
    logger.debug(f"[HoomanLabs] Background dispatch thread started for log_id={log_id}")
    return log
