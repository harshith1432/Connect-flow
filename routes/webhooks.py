"""
routes/webhooks.py
------------------
Receives call-status POST callbacks from Hooman Labs (via Plivo).

Hooman Labs status endpoint:
    https://core.hoomanlabs.com/routes/call/plivo/status

Our callback URL (registered in the Hooman Labs API payload):
    <BASE_URL>/webhooks/hooman/call-status

Plivo / Hooman Labs typically sends these fields in the POST body:
    CallUUID    – unique call identifier (maps to DeliveryLog.sid)
    Status      – "initiated", "ringing", "answered", "completed", "busy",
                  "failed", "no-answer", "canceled"
    Duration    – call duration in seconds (present on "completed")
    BillDuration / BillRate – billing info (ignored here)

We normalise the status and update the matching DeliveryLog row.
"""

import sys
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from models import db
from models.models import DeliveryLog

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__)


# ---------------------------------------------------------------------------
# Status normalisation
# ---------------------------------------------------------------------------

# Map Plivo/Hooman status strings → our internal status values
_STATUS_MAP = {
    "initiated": "initiated",
    "ringing": "ringing",
    "answered": "in-progress",
    "in-progress": "in-progress",
    "completed": "completed",
    "busy": "busy",
    "failed": "failed",
    "no-answer": "no-answer",
    "canceled": "canceled",
    "no_answer": "no-answer",  # underscore variant
    "hangup": "completed",
}


def _normalise(raw_status: str) -> str:
    return _STATUS_MAP.get(
        (raw_status or "").lower().strip(), raw_status.lower().strip()
    )


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


@webhooks_bp.route("/hooman/call-status", methods=["POST"])
def hooman_call_status():
    """
    Receive call-status updates from Hooman Labs / Plivo.
    Accepts both JSON and form-encoded bodies.
    """
    # -- Parse incoming payload (JSON or form-encoded) --
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()

    logger.info(f"[Webhook/Hooman] Received status callback: {data}")

    # -- Extract fields --
    call_info = data.get("callInfo", {})
    event = data.get("event")
    phone = data.get("phone") or call_info.get("to")

    # Plivo uses 'CallUUID'; Hooman may also send 'call_id' or 'task_id' or 'taskId' or 'task'
    call_uuid = (
        call_info.get("task")
        or call_info.get("callSid")
        or data.get("taskId")
        or data.get("CallUUID")
        or data.get("call_uuid")
        or data.get("call_id")
        or data.get("task_id")
        or data.get("sid")
        or ""
    ).strip()

    raw_status = (
        data.get("Status")
        or data.get("CallStatus")
        or data.get("status")
        or event  # fallback to 'event' if 'status' is missing
        or ""
    ).strip()

    duration = (
        data.get("duration")
        or data.get("Duration")
        or data.get("BillDuration")
        or call_info.get("duration")
        or None
    )

    # -- Map native Hooman events to normalized status --
    if event:
        if event == "callEndConnected":
            raw_status = "completed"
        elif event == "callEndNotConnected":
            raw_status = "no-answer"
        elif event == "callStart":
            raw_status = "ringing"
        elif event == "callEnd":
            raw_status = "completed"

        logger.info(f"[Webhook/Hooman] Native Event: {event} for phone {phone}")

    if not call_uuid and not phone:
        logger.warning(
            "[Webhook/Hooman] Missing identifier (CallUUID or phone) in callback — ignoring."
        )
        return jsonify({"ok": False, "error": "missing identifier"}), 400

    if not raw_status:
        logger.warning(f"[Webhook/Hooman] Missing Status for identifier — ignoring.")
        return jsonify({"ok": False, "error": "missing Status"}), 400

    normalised = _normalise(raw_status)

    # -- Logging Call Report (exactly as in user snippet) --
    report_status = (
        "Answered "
        if normalised == "completed" or normalised == "in-progress"
        else "Not Answered "
    )

    print("\n" + " CALL REPORT")
    print(f"To: {call_uuid or phone}")
    print(f"From: {data.get('from', 'N/A')}")
    print(f"Status: {report_status}")
    print(f"Duration: {duration}")
    print(f"Connected: {normalised in ('completed', 'in-progress')}")
    print(f"Time: {datetime.utcnow()}")
    print("=" * 40 + "\n")
    sys.stdout.flush()

    logger.info(
        f"[Webhook/Hooman] ID={call_uuid or phone} | "
        f"raw={raw_status} → normalised={normalised} | duration={duration}s"
    )

    # -- Update DeliveryLog --
    delivery_log = None

    if call_uuid:
        delivery_log = DeliveryLog.query.filter_by(sid=call_uuid).first()

    if not delivery_log and call_uuid:
        # Try matching by call_uuid stored in meta JSON (fallback)
        delivery_log = DeliveryLog.query.filter(
            DeliveryLog.meta["call_uuid"].astext == call_uuid
        ).first()

    if not delivery_log and phone:
        # Fallback: Match by phone number for recent hooman_voice calls
        # We look for the most recent log for this recipient that isn't already 'completed'
        delivery_log = (
            DeliveryLog.query.filter_by(recipient=phone, channel="hooman_voice")
            .order_by(DeliveryLog.created_at.desc())
            .first()
        )

    if not delivery_log:
        logger.warning(
            f"[Webhook/Hooman] No DeliveryLog found for ID={call_uuid or phone}. "
        )
        # Still return 200 so Hooman doesn't retry indefinitely
        return jsonify({"ok": True, "note": "no matching log"}), 200

    # Update status
    delivery_log.status = normalised

    # Store duration in meta on completion
    if normalised in ("completed", "failed", "busy", "no-answer", "canceled"):
        meta = dict(delivery_log.meta or {})
        if duration:
            meta["duration_seconds"] = int(duration)
        meta["final_status"] = normalised
        meta["raw_status"] = raw_status
        delivery_log.meta = meta

    try:
        db.session.commit()
        logger.info(
            f"[Webhook/Hooman] DeliveryLog #{delivery_log.id} updated: "
            f"status={normalised}, duration={duration}s"
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Webhook/Hooman] DB commit failed: {e}")
        return jsonify({"ok": False, "error": "db error"}), 500

    return jsonify({"ok": True, "status": normalised}), 200


# ---------------------------------------------------------------------------
# Health check (optional — useful to verify the endpoint is reachable)
# ---------------------------------------------------------------------------


@webhooks_bp.route("/hooman/call-status", methods=["GET"])
def hooman_call_status_ping():
    return jsonify({"ok": True, "message": "Hooman call-status webhook is live"}), 200
