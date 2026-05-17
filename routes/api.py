from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db
from models.models import ModuleField, ModuleRecord, DeliveryLog, ModuleRecordValue

api_bp = Blueprint("api", __name__)


@api_bp.route("/check-uniqueness", methods=["POST"])
@login_required
def check_uniqueness():
    data = request.get_json()
    field_id = data.get("field_id")
    value = data.get("value")
    record_id = data.get("record_id")  # To exclude if editing

    if not field_id or value is None:
        return jsonify({"error": "Missing parameters"}), 400

    field = db.get_or_404(ModuleField, field_id)

    # Check if field is unique
    if not field.is_unique:
        return jsonify({"unique": True})

    # Check database for duplicate (case-insensitive)
    from sqlalchemy import func

    query = (
        db.session.query(ModuleRecordValue)
        .join(ModuleRecord)
        .filter(
            ModuleRecordValue.field_id == field.id,
            func.lower(ModuleRecordValue.value) == func.lower(str(value)),
            ModuleRecord.module_id == field.module_id,
        )
    )

    if record_id:
        query = query.filter(ModuleRecord.id != record_id)

    exists = query.first() is not None

    return jsonify({"unique": not exists})


@api_bp.route("/twilio/message-status", methods=["GET", "POST"])
def twilio_message_status():
    """
    Webhook for Twilio Message Status Updates.
    Twilio posts: MessageSid, MessageStatus, To, etc.
    """
    if request.method == "GET":
        print("[TWILIO WEBHOOK] Manual GET check received! URL is working.")
        return "Webhook is active. Send POST for data.", 200

    from models.models import DeliveryLog

    print(f"[TWILIO WEBHOOK] Full Request Data: {dict(request.form)}")
    sid = request.form.get("MessageSid")
    status = request.form.get("MessageStatus")
    error_code = request.form.get("ErrorCode")

    print(f"[TWILIO WEBHOOK] Message SID: {sid}, Status: {status}, Error: {error_code}")

    if sid:
        log = DeliveryLog.query.filter_by(sid=sid).first()
        if log:
            print(
                f"[TWILIO WEBHOOK] Found log for SID {sid}. Updating status to {status}"
            )
            log.status = status
            if error_code:
                log.error = f"Twilio Error: {error_code}"
            db.session.commit()
        else:
            print(f"[TWILIO WEBHOOK] WARNING: No log found in DB for SID {sid}")

    return "OK", 200


@api_bp.route("/twilio/voice-status", methods=["GET", "POST"])
def twilio_voice_status():
    """
    Webhook for Twilio Voice Call Status Updates.
    Twilio posts: CallSid, CallStatus, To, etc.
    """
    if request.method == "GET":
        print("[TWILIO WEBHOOK] Manual GET check received for Voice! URL is working.")
        return "Webhook is active. Send POST for data.", 200

    from models.models import DeliveryLog

    print(f"[TWILIO WEBHOOK VOICE] Full Request Data: {dict(request.form)}")
    sid = request.form.get("CallSid")
    status = request.form.get("CallStatus")

    print(f"[TWILIO WEBHOOK] Call SID: {sid}, Status: {status}")

    if sid:
        log = DeliveryLog.query.filter_by(sid=sid).first()
        if log:
            print(
                f"[TWILIO WEBHOOK] Found log for SID {sid}. Updating status to {status}"
            )
            log.status = status
            db.session.commit()
        else:
            print(f"[TWILIO WEBHOOK] WARNING: No log found in DB for SID {sid}")

    return "OK", 200


@api_bp.route("/hooman/callback", methods=["POST"])
def hooman_callback():
    """
    Webhook for Hooman Labs Call Status Updates.
    """
    data = request.get_json()
    if not data:
        # Fallback to form data if not JSON
        data = request.form.to_dict()

    if not data:
        print("[HOOMAN CALLBACK] No data received")
        return "No data", 400

    print(f"[HOOMAN CALLBACK] Received data: {data}")

    sid = data.get("call_id") or data.get("sid")
    status = data.get("status")
    error = data.get("error")

    if sid:
        log = DeliveryLog.query.filter_by(sid=sid).first()
        if log:
            print(
                f"[HOOMAN CALLBACK] Found log for SID {sid}. Updating status to {status}"
            )
            log.status = status
            if error:
                log.error = error
            db.session.commit()
        else:
            print(f"[HOOMAN CALLBACK] WARNING: No log found in DB for SID {sid}")

    return "OK", 200
