"""
HumanLab Provider — Campaign Call Integration
==============================================
Single source of truth for all Hooman Labs API calls.
Matches the exact logic from the standalone working script.
"""

import logging
import sys
import requests
import json
import time
import pytz
from datetime import datetime, timedelta
from flask import current_app

logger = logging.getLogger(__name__)

HOOMAN_TASKS_URL = "https://api.hoomanlabs.com/routes/v1/tasks/"

# ---------------------------------------------------------------
# CENTRAL CONFIG — Single source of truth
# ---------------------------------------------------------------

def get_hooman_config(organization_id=None):
    """
    Returns the Hooman Labs configuration dict.
    
    API key and from_number are loaded ONLY from the organization's
    hooman_config column in the database. Each org has its own
    credentials set by the platform admin.
    
    Campaign/Agent IDs come from app.config (.env) as they are global.
    
    Returns:
        {
            "api_key": str,
            "from_number": str,
            "campaign": str,
            "organization_id": str,
        }
    """
    app = current_app._get_current_object()
    api_key = ""
    from_number = ""

    # --- Load from Organization DB config (per-org credentials) ---
    if organization_id:
        from app.models import Organization
        from app.extensions import db
        org = db.session.get(Organization, organization_id)
        if org:
            config = org.hooman_config or {}
            # Also check nested twilio_config.hooman_labs for legacy orgs
            if not config and org.twilio_config:
                config = org.twilio_config.get("hooman_labs", {})
            api_key = (config.get("api_key") or "").strip()
            from_number = (config.get("number") or "").strip()
            
            if not api_key:
                logger.warning(
                    f"[HoomanLabs] Organization {organization_id} ({org.name}) "
                    f"has NO api_key in hooman_config. "
                    f"Platform admin must set it via Org Settings > Communication."
                )
            if not from_number:
                logger.warning(
                    f"[HoomanLabs] Organization {organization_id} ({org.name}) "
                    f"has NO from_number in hooman_config."
                )
    else:
        logger.error("[HoomanLabs] get_hooman_config called without organization_id!")

    return {
        "api_key": api_key,
        "from_number": from_number,
        "campaign": (app.config.get("HOOMAN_CAMPAIGN_ID") or "").strip(),
        "organization_id": (app.config.get("HOOMAN_ORGANIZATION_ID") or "").strip(),
    }


def _resolve_agent_and_campaign(language, app):
    """Resolve agent ID and campaign ID based on language."""
    LANGUAGE_CONFIG_MAP = {
        "Telugu":    {"agent": "HOOMAN_AGENT_TELUGU",    "campaign": "HOOMAN_CAMPAIGN_ID_TELUGU"},
        "Malayalam": {"agent": "HOOMAN_AGENT_MALAYALAM", "campaign": "HOOMAN_CAMPAIGN_ID_MALAYALAM"},
        "Marathi":   {"agent": "HOOMAN_AGENT_MARATHI",   "campaign": "HOOMAN_CAMPAIGN_ID_MARATHI"},
        "Tamil":     {"agent": "HOOMAN_AGENT_TAMIL",     "campaign": "HOOMAN_CAMPAIGN_ID_TAMIL"},
        "Kannada":   {"agent": "HOOMAN_AGENT_KANNADA",   "campaign": "HOOMAN_CAMPAIGN_ID_KANNADA"},
        "Hindi":     {"agent": "HOOMAN_AGENT_HINDI",     "campaign": "HOOMAN_CAMPAIGN_ID_HINDI"},
        "English":   {"agent": "HOOMAN_AGENT_ENGLISH",   "campaign": "HOOMAN_CAMPAIGN_ID_ENGLISH"},
        "Punjabi":   {"agent": "HOOMAN_AGENT_PUNJABI",   "campaign": ""},
        "Gujarati":  {"agent": "HOOMAN_AGENT_GUJARATI",  "campaign": ""},
    }
    
    config = LANGUAGE_CONFIG_MAP.get(language, {})
    
    # Agent
    agent_id = ""
    agent_key = config.get("agent")
    if agent_key:
        agent_id = (app.config.get(agent_key) or "").strip()
    if not agent_id:
        agent_id = (app.config.get("HOOMAN_AGENT_VOICE_CALL") or "").strip()
    
    # Campaign
    campaign_id = ""
    campaign_key = config.get("campaign")
    if campaign_key:
        campaign_id = (app.config.get(campaign_key) or "").strip()
    if not campaign_id:
        campaign_id = (app.config.get("HOOMAN_CAMPAIGN_ID") or "").strip()
    
    return agent_id, campaign_id


# ---------------------------------------------------------------
# MAIN PROVIDER
# ---------------------------------------------------------------

class HumanLabProvider:
    @staticmethod
    def start_call(payload_data, organization_id=None):
        """
        Start a Hooman Labs voice call.
        
        payload_data: {
            "campaign_id": int,     (internal campaign ID)
            "phone": str,
            "script": str,
            "language": str,
        }
        
        Returns:
            {"success": True,  "task_id": "...", "status": "queued"}
            {"success": False, "error": "..."}
        """
        print(f"\n[HOOMAN] start_call invoked", file=sys.stderr, flush=True)
        app = current_app._get_current_object()
        
        phone = payload_data.get("phone", "")
        script = payload_data.get("script", "")
        language = payload_data.get("language", "English")
        
        # ---- GET CONFIG (single source of truth) ----
        hooman_cfg = get_hooman_config(organization_id)
        api_key = hooman_cfg["api_key"]
        from_number = hooman_cfg["from_number"]
        hooman_org_id = hooman_cfg["organization_id"]
        
        # Resolve language-specific agent & campaign
        agent_id, campaign_id = _resolve_agent_and_campaign(language, app)
        
        # ---- VALIDATION (Requirement #4) ----
        errors = []
        if not api_key:
            errors.append(
                "HOOMAN_API_KEY is empty for this organization. "
                "Platform admin must configure it in "
                "Org Detail > Communication Settings > Hooman Labs API Key."
            )
        if not campaign_id:
            errors.append("HOOMAN_CAMPAIGN_ID is empty.")
        if not agent_id:
            errors.append("HOOMAN_AGENT is empty for language: " + language)
        if not phone:
            errors.append("Phone number is empty.")
        
        if errors:
            error_msg = " | ".join(errors)
            print(f"[HOOMAN] VALIDATION FAILED: {error_msg}", file=sys.stderr, flush=True)
            logger.error(f"[HumanLabProvider] Validation failed: {error_msg}")
            return {"success": False, "error": error_msg}
        
        # ---- DEBUG LOGGING (Requirement #5 — no full token) ----
        token_preview = api_key[:6] + "****" if len(api_key) > 6 else "****"
        print(f"[HOOMAN] TOKEN EXISTS: YES ({token_preview})", file=sys.stderr, flush=True)
        print(f"[HOOMAN] AGENT: {agent_id}", file=sys.stderr, flush=True)
        print(f"[HOOMAN] CAMPAIGN: {campaign_id}", file=sys.stderr, flush=True)
        print(f"[HOOMAN] PHONE: {phone}", file=sys.stderr, flush=True)
        print(f"[HOOMAN] FROM: {from_number}", file=sys.stderr, flush=True)
        print(f"[HOOMAN] URL: {HOOMAN_TASKS_URL}", file=sys.stderr, flush=True)
        
        # ---- BUILD REQUEST (exact match to working hooman_labs.py) ----
        base_url = (app.config.get("PUBLIC_BASE_URL") or app.config.get("BASE_URL") or "").strip().rstrip("/")
        status_callback_url = ""
        if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url:
            status_callback_url = f"{base_url}/worker/api/humanlab/webhook"
        
        import pytz as _pytz
        india = _pytz.timezone("Asia/Kolkata")
        now = datetime.now(india)
        start_after = now + timedelta(minutes=1)
        end_after = now + timedelta(hours=24)
        
        payload = {
            "campaign": str(campaign_id),
            "company": "default",
            "agent": str(agent_id) if agent_id else "",
            "phone": str(phone),
            "from": str(from_number) if from_number else "",
            "start": 0000,           # start window (HHMM)
            "end": 4759,             # end window (HHMM) — valid for 24 hrs
            "timezone": "Asia/Kolkata",
            "startAfter": start_after.isoformat(),
            "endAfter": end_after.isoformat(),
            "priority": [1],
            "retries": 1,
            "intervals": [120],      # retry after 120 seconds
            "context": {
                "message": str(script) if script else "",
            },
        }
        
        if status_callback_url:
            payload["statusCallbackUrl"] = str(status_callback_url)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if hooman_org_id:
            headers["X-Hooman-Organization"] = str(hooman_org_id)

        # Log header safely (mask token)
        safe_headers = dict(headers)
        safe_headers["Authorization"] = f"Bearer {token_preview}"
        print(f"[HOOMAN] Headers: {safe_headers}", file=sys.stderr, flush=True)
        print(f"[HOOMAN] Payload: {json.dumps(payload, indent=2)}", file=sys.stderr, flush=True)

        # ---- SEND REQUEST ----
        try:
            logger.info(f"[HumanLabProvider] Calling {phone} with agent {agent_id}")
            response = requests.post(HOOMAN_TASKS_URL, json=payload, headers=headers, timeout=30)
            
            status_code = response.status_code
            response_text = response.text
            
            print(f"[HOOMAN] Response: {status_code}", file=sys.stderr, flush=True)
            print(f"[HOOMAN] Body: {response_text[:500]}", file=sys.stderr, flush=True)
            
            # ---- RESPONSE HANDLING (Requirement #6) ----
            if status_code in (200, 201, 202):
                resp_json = response.json()
                task_id = str(
                    resp_json.get("taskId")
                    or resp_json.get("task_id")
                    or resp_json.get("task")
                    or resp_json.get("id")
                    or ""
                )
                print(f"[HOOMAN] CALL CREATED - Task ID: {task_id}", file=sys.stderr, flush=True)
                return {"success": True, "task_id": task_id, "status": "queued"}
            
            elif status_code == 401:
                error = f"AUTH FAILED (401): Invalid or expired API key. Response: {response_text}"
                print(f"[HOOMAN] {error}", file=sys.stderr, flush=True)
                logger.error(f"[HumanLabProvider] {error}")
                return {"success": False, "error": error, "status": "auth_failed"}
            
            elif status_code == 422:
                error = f"PAYLOAD ISSUE (422): {response_text}"
                print(f"[HOOMAN] {error}", file=sys.stderr, flush=True)
                logger.error(f"[HumanLabProvider] {error}")
                return {"success": False, "error": error, "status": "invalid_payload"}
            
            elif status_code >= 500:
                error = f"SERVER ERROR ({status_code}): {response_text} — will be retried"
                print(f"[HOOMAN] {error}", file=sys.stderr, flush=True)
                logger.error(f"[HumanLabProvider] {error}")
                return {"success": False, "error": error, "status": "server_error"}
            
            else:
                error = f"HTTP {status_code}: {response_text}"
                print(f"[HOOMAN] FAILED: {error}", file=sys.stderr, flush=True)
                logger.error(f"[HumanLabProvider] {error}")
                return {"success": False, "error": error}
                
        except requests.exceptions.Timeout:
            error = "Request timed out after 30 seconds"
            print(f"[HOOMAN] TIMEOUT: {error}", file=sys.stderr, flush=True)
            logger.error(f"[HumanLabProvider] {error}")
            return {"success": False, "error": error}
        except requests.exceptions.ConnectionError as e:
            error = f"Connection error: {str(e)}"
            print(f"[HOOMAN] CONNECTION ERROR: {error}", file=sys.stderr, flush=True)
            logger.error(f"[HumanLabProvider] {error}")
            return {"success": False, "error": error}
        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            print(f"[HOOMAN] EXCEPTION: {error}", file=sys.stderr, flush=True)
            logger.error(f"[HumanLabProvider] {error}")
            return {"success": False, "error": error}
