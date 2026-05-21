"""
app/features/webhooks/routes.py
------------------
Receives call-status POST callbacks from Hooman Labs (via Plivo).
"""

import sys
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models import DeliveryLog

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__)

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

    # -- Logging Call Report --
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
    from app.models import CampaignTarget
    target = None
    delivery_log = None

    w_conv_id = data.get("conversationId") or ""
    w_task_id = data.get("taskId") or call_info.get("task") or ""
    w_phone = phone or ""

    # 1. By conversationId
    if w_conv_id:
        target = CampaignTarget.query.filter_by(conversation_id=w_conv_id).first()
        if not target:
            delivery_log = DeliveryLog.query.filter_by(sid=w_conv_id).first()

    # 2. By taskId
    if not target and not delivery_log and w_task_id:
        target = CampaignTarget.query.filter_by(conversation_id=w_task_id).first()
        if not target:
            delivery_log = DeliveryLog.query.filter_by(sid=w_task_id).first()

    # 3. By normalized phone
    if not target and not delivery_log and w_phone:
        import re
        n_phone = re.sub(r'\D', '', w_phone)
        if n_phone.startswith('91') and len(n_phone) == 12:
            n_phone = n_phone[2:]
        elif len(n_phone) > 10:
            n_phone = n_phone[-10:]

        if n_phone:
            delivery_log = DeliveryLog.query.filter(
                DeliveryLog.recipient.like(f"%{n_phone}")
            ).order_by(DeliveryLog.created_at.desc()).first()

    if target and not delivery_log:
        delivery_log = DeliveryLog.query.filter_by(
            campaign_id=target.campaign_id,
            record_id=target.record_id
        ).order_by(DeliveryLog.created_at.desc()).first()

    if not delivery_log:
        logger.warning(
            f"[Webhook/Hooman] No DeliveryLog found for ID={call_uuid or phone}. "
        )
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
        # Trigger CampaignExecutionService for retry and fallback logic
        from flask import current_app
        from app.services.campaign_runner import CampaignExecutionService
        app_obj = current_app._get_current_object()
        webhook_payload = {
            "conversationId": call_uuid,
            "connected": normalised in ("completed", "in-progress"),
            "duration": int(duration) if duration else 0,
            "outcome": normalised,
            "endReason": raw_status,
            "taskCompleted": normalised == "completed",
            "callInfo": {"to": phone}
        }
        CampaignExecutionService.handle_webhook(app_obj, webhook_payload)
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Webhook/Hooman] DB commit failed: {e}")
        return jsonify({"ok": False, "error": "db error"}), 500

    return jsonify({"ok": True, "status": normalised}), 200


@webhooks_bp.route("/hooman/call-status", methods=["GET"])
def hooman_call_status_ping():
    return jsonify({"ok": True, "message": "Hooman call-status webhook is live"}), 200
