from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import ModuleField, ModuleRecord, DeliveryLog, ModuleRecordValue

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


@api_bp.route("/create-order", methods=["POST"])
@login_required
def create_order():
    import uuid
    from app.models import Plan
    from app.services.payment_gateway_service import PaymentGatewayService
    from app.services.payment_dispatcher import PaymentDispatcher

    data = request.get_json() or {}
    plan_id = data.get("plan_id")
    gateway_id = data.get("gateway_id")
    
    if not plan_id:
        return jsonify({"error": "Missing plan_id"}), 400
    if not gateway_id:
        return jsonify({"error": "Missing gateway_id"}), 400

    plan = db.session.get(Plan, plan_id)
    if not plan:
        return jsonify({"error": "Plan not found"}), 404

    gateway = PaymentGatewayService.get_gateway_by_id(gateway_id)
    if not gateway or not gateway.active:
        return jsonify({"error": "Selected payment gateway is unavailable"}), 400

    amount_paise = int(plan.price * 100)
    if amount_paise < 100:
        amount_paise = 100

    try:
        receipt_id = f"rcpt_{uuid.uuid4().hex[:10]}"
        order_data = PaymentDispatcher.create_order(gateway, amount_paise, "INR", receipt_id)
        order_data["sandbox"] = gateway.deployment_mode == "test"
        return jsonify(order_data)
    except Exception as e:
        print(f"[ORDER ERROR] {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/verify-payment", methods=["POST"])
@login_required
def verify_payment():
    from datetime import datetime, timedelta
    from app.models import Plan, Subscription, Payment
    from app.services.payment_gateway_service import PaymentGatewayService
    from app.services.payment_dispatcher import PaymentDispatcher

    data = request.get_json() or {}
    plan_id = data.get("plan_id")
    gateway_id = data.get("gateway_id")

    if not all([plan_id, gateway_id]):
        return jsonify({"error": "Missing parameters"}), 400

    plan = db.session.get(Plan, plan_id)
    if not plan:
        return jsonify({"error": "Plan not found"}), 404
        
    gateway = PaymentGatewayService.get_gateway_by_id(gateway_id)
    if not gateway:
        return jsonify({"error": "Gateway not found"}), 404

    try:
        # Verify payment with the specific gateway
        is_valid, message = PaymentDispatcher.verify_payment(gateway, data)
        
        if not is_valid:
            return jsonify({"error": message}), 400

        # Success!
        org = current_user.organization

        sub = Subscription.query.filter_by(organization_id=org.id).first()
        if not sub:
            sub = Subscription(organization_id=org.id)
            db.session.add(sub)

        sub.plan = plan.name
        sub.status = "active"
        sub.billing_interval = plan.billing_interval
        sub.starts_at = datetime.utcnow()

        if plan.billing_interval == "yearly":
            sub.expires_at = sub.starts_at + timedelta(days=365)
        else:
            sub.expires_at = sub.starts_at + timedelta(days=30)

        # Record Payment for Revenue Dashboard with gateway info
        transaction_id = data.get("razorpay_payment_id") or data.get("stripe_payment_id") or "txn_unknown"
        
        payment = Payment(
            organization_id=org.id,
            amount=plan.price,
            status="completed",
            gateway_id=gateway.id,
            gateway_name=gateway.name,
            gateway_provider=gateway.provider,
            gateway_mode=gateway.deployment_mode,
            transaction_id=transaction_id,
            gateway_response=data,
            meta={
                "plan_name": plan.name,
                "method": f"{gateway.name} Checkout"
            },
        )
        db.session.add(payment)
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        print(f"[VERIFY ERROR] {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/ce/create-order", methods=["POST"])
@login_required
def ce_create_order():
    import uuid
    from app.models import Campaign
    from app.models.campaign_express import CampaignExpressPayment
    from app.services.payment_gateway_service import PaymentGatewayService
    from app.services.payment_dispatcher import PaymentDispatcher

    data = request.get_json() or {}
    campaign_id = data.get("campaign_id")
    gateway_id = data.get("gateway_id")

    if not campaign_id or not gateway_id:
        return jsonify({"error": "Missing campaign_id or gateway_id"}), 400

    campaign = Campaign.query.filter_by(id=campaign_id, campaign_express_user_id=current_user.id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    gateway = PaymentGatewayService.get_gateway_by_id(gateway_id)
    if not gateway or not gateway.active:
        return jsonify({"error": "Selected payment gateway is unavailable"}), 400

    # Retrieve pending CampaignExpressPayment for this campaign
    payment = CampaignExpressPayment.query.filter_by(
        campaign_id=campaign.id, user_id=current_user.id, status="pending"
    ).order_by(CampaignExpressPayment.created_at.desc()).first()

    if not payment:
        return jsonify({"error": "No pending payment found for this campaign"}), 400

    amount_paise = int(payment.amount * 100)
    if amount_paise < 100:
        amount_paise = 100  # min amount for Razorpay

    try:
        receipt_id = f"ce_rcpt_{uuid.uuid4().hex[:10]}"
        order_data = PaymentDispatcher.create_order(gateway, amount_paise, "INR", receipt_id)
        order_data["sandbox"] = gateway.deployment_mode == "test"
        return jsonify(order_data)
    except Exception as e:
        print(f"[CE ORDER ERROR] {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/ce/verify-payment", methods=["POST"])
@login_required
def ce_verify_payment():
    from datetime import datetime
    from app.models import Campaign
    from app.models.campaign_express import CampaignExpressPayment
    from app.services.payment_gateway_service import PaymentGatewayService
    from app.services.payment_dispatcher import PaymentDispatcher
    from app.services.ce_number_allocator import CeNumberAllocator
    from app.services.campaign_runner import CampaignExecutionService

    data = request.get_json() or {}
    campaign_id = data.get("campaign_id")
    gateway_id = data.get("gateway_id")

    if not all([campaign_id, gateway_id]):
        return jsonify({"error": "Missing parameters"}), 400

    campaign = Campaign.query.filter_by(id=campaign_id, campaign_express_user_id=current_user.id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    gateway = PaymentGatewayService.get_gateway_by_id(gateway_id)
    if not gateway:
        return jsonify({"error": "Gateway not found"}), 404

    payment = CampaignExpressPayment.query.filter_by(
        campaign_id=campaign.id, user_id=current_user.id, status="pending"
    ).order_by(CampaignExpressPayment.created_at.desc()).first()

    if not payment:
        return jsonify({"error": "No pending payment record found"}), 404

    try:
        is_valid, message = PaymentDispatcher.verify_payment(gateway, data)
        if not is_valid:
            return jsonify({"error": message}), 400

        # Signature verification success! Update payment
        transaction_id = data.get("razorpay_payment_id") or data.get("stripe_payment_id") or "ce_txn_unknown"
        payment.status = "completed"
        payment.gateway_id = gateway.id
        payment.gateway_name = gateway.name
        payment.gateway_provider = gateway.provider
        payment.gateway_mode = gateway.deployment_mode
        payment.transaction_id = transaction_id
        payment.gateway_response = data
        payment.completed_at = datetime.utcnow()

        # Update campaign status
        campaign.status = "ready"
        db.session.commit()

        # Allocate a pool number and trigger campaign execution
        assigned_number = CeNumberAllocator.allocate(campaign.id)
        if not assigned_number:
            campaign.status = "queued"
            db.session.commit()
            print(f"[CE EXECUTION] No active numbers for campaign {campaign.id}. Status set to queued.")
        else:
            campaign.status = "running"
            db.session.commit()
            try:
                from flask import current_app
                app_obj = current_app._get_current_object()
                CampaignExecutionService.start(campaign.id)
                print(f"[CE EXECUTION] Successfully started campaign {campaign.id} with number {assigned_number.number}")
            except Exception as run_err:
                print(f"[CE EXECUTION ERROR] Failed to start runner: {run_err}")
                # Release number back to pool on failure
                CeNumberAllocator.release(campaign.id)
                campaign.status = "ready"
                db.session.commit()
                return jsonify({"error": f"Failed to start campaign: {str(run_err)}"}), 500

        return jsonify({"success": True})

    except Exception as e:
        print(f"[CE VERIFY ERROR] {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/search", methods=["GET"])
@login_required
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})

    results = []
    user_type = None
    if hasattr(current_user, "role") and current_user.role == "platform_owner":
        user_type = "platform_admin"
    elif current_user.role == "org_admin":
        user_type = "org_admin"
    else:
        user_type = "worker"

    if user_type == "platform_admin":
        from app.models import Organization, Plan
        orgs = Organization.query.filter(Organization.name.ilike(f"%{q}%")).limit(5).all()
        for o in orgs:
            results.append({
                "category": "Organizations",
                "title": o.name,
                "subtitle": f"Status: {o.status.upper()}",
                "link": "/platform"
            })
        plans = Plan.query.filter(Plan.name.ilike(f"%{q}%")).limit(5).all()
        for p in plans:
            results.append({
                "category": "Plans",
                "title": p.name,
                "subtitle": f"Price: INR {p.price}",
                "link": "/platform/plans"
            })
    elif user_type == "org_admin":
        from app.models import OrganizationUser, Campaign, Module
        workers = OrganizationUser.query.filter(
            OrganizationUser.organization_id == current_user.organization_id,
            OrganizationUser.role == "worker",
            (OrganizationUser.full_name.ilike(f"%{q}%") | OrganizationUser.email.ilike(f"%{q}%"))
        ).limit(5).all()
        for w in workers:
            results.append({
                "category": "Workers",
                "title": w.full_name or w.email,
                "subtitle": w.designation or "Worker",
                "link": "/org/workers"
            })
        campaigns = Campaign.query.filter(
            Campaign.organization_id == current_user.organization_id,
            Campaign.name.ilike(f"%{q}%")
        ).limit(5).all()
        for c in campaigns:
            results.append({
                "category": "Campaigns",
                "title": c.name,
                "subtitle": f"Status: {c.status}",
                "link": "/org/campaigns"
            })
        modules = Module.query.filter(
            Module.organization_id == current_user.organization_id,
            Module.name.ilike(f"%{q}%")
        ).limit(5).all()
        for m in modules:
            results.append({
                "category": "Modules",
                "title": m.name,
                "subtitle": "Custom CRM Form",
                "link": "/org/dashboard"
            })
    elif user_type == "worker":
        from app.models import Module
        modules = Module.query.filter(
            Module.organization_id == current_user.organization_id,
            Module.name.ilike(f"%{q}%")
        ).limit(5).all()
        for m in modules:
            results.append({
                "category": "CRM Modules",
                "title": m.name,
                "subtitle": "CRM Records",
                "link": "/worker/dashboard"
            })

    return jsonify({"results": results})


@api_bp.route("/notifications", methods=["GET"])
@login_required
def get_notifications():
    from app.models import DashboardNotification
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    
    if is_platform:
        notifs = DashboardNotification.query.filter_by(
            platform_admin_id=current_user.id
        ).order_by(DashboardNotification.created_at.desc()).limit(20).all()
    else:
        notifs = DashboardNotification.query.filter_by(
            user_id=current_user.id,
            organization_id=current_user.organization_id
        ).order_by(DashboardNotification.created_at.desc()).limit(20).all()
        
    return jsonify({
        "notifications": [n.to_dict() for n in notifs],
        "unread_count": sum(1 for n in notifs if not n.is_read)
    })


@api_bp.route("/notifications/read", methods=["POST"])
@login_required
def mark_notifications_read():
    from app.models import DashboardNotification
    data = request.get_json() or {}
    notif_id = data.get("id")
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    
    if notif_id:
        if is_platform:
            notif = DashboardNotification.query.filter_by(
                id=notif_id, platform_admin_id=current_user.id
            ).first()
        else:
            notif = DashboardNotification.query.filter_by(
                id=notif_id, user_id=current_user.id, organization_id=current_user.organization_id
            ).first()
        if notif:
            notif.is_read = True
            db.session.commit()
    else:
        if is_platform:
            notifs = DashboardNotification.query.filter_by(
                platform_admin_id=current_user.id, is_read=False
            ).all()
        else:
            notifs = DashboardNotification.query.filter_by(
                user_id=current_user.id, organization_id=current_user.organization_id, is_read=False
            ).all()
        for n in notifs:
            n.is_read = True
        db.session.commit()
        
    return jsonify({"success": True})


@api_bp.route("/chat/contacts", methods=["GET"])
@login_required
def chat_contacts():
    from app.models import ChatMessage, OrganizationUser
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    contacts = []
    
    if is_platform:
        # Platform Admin: get list of Organization Admins who have initiated a chat
        sender_ids = db.session.query(ChatMessage.sender_id).filter(
            ChatMessage.sender_type == "org_admin"
        ).distinct().all()
        sender_ids = [s[0] for s in sender_ids]
        
        admins = OrganizationUser.query.filter(
            OrganizationUser.id.in_(sender_ids),
            OrganizationUser.role == "org_admin"
        ).all()
        for admin in admins:
            org_name = admin.organization.name if admin.organization else "Organization"
            contacts.append({
                "id": admin.id,
                "name": admin.full_name or admin.email,
                "role": "org_admin",
                "subtitle": org_name,
                "avatar": (admin.full_name or admin.email)[0].upper()
            })
    elif current_user.role == "org_admin":
        workers = OrganizationUser.query.filter_by(
            organization_id=current_user.organization_id,
            role="worker"
        ).all()
        for worker in workers:
            contacts.append({
                "id": worker.id,
                "name": worker.full_name or worker.email,
                "role": "worker",
                "subtitle": worker.designation or "Worker Workspace",
                "avatar": (worker.full_name or worker.email)[0].upper()
            })
    elif current_user.role == "worker":
        admins = OrganizationUser.query.filter_by(
            organization_id=current_user.organization_id,
            role="org_admin"
        ).all()
        for admin in admins:
            contacts.append({
                "id": admin.id,
                "name": admin.full_name or admin.email,
                "role": "org_admin",
                "subtitle": "Organization Administrator",
                "avatar": (admin.full_name or admin.email)[0].upper()
            })
            
    return jsonify({"contacts": contacts})


@api_bp.route("/chat/messages", methods=["GET"])
@login_required
def chat_messages():
    from app.models import ChatMessage
    contact_id = request.args.get("contact_id", type=int)
    contact_role = request.args.get("contact_role")
    
    if contact_id is None or not contact_role:
        return jsonify({"error": "Missing parameters"}), 400
        
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    messages = []
    
    if is_platform:
        messages = ChatMessage.query.filter(
            ((ChatMessage.sender_type == "platform_admin") & (ChatMessage.recipient_type == "org_admin") & (ChatMessage.recipient_id == contact_id)) |
            ((ChatMessage.sender_type == "org_admin") & (ChatMessage.sender_id == contact_id) & (ChatMessage.recipient_type == "platform_admin"))
        ).order_by(ChatMessage.created_at.asc()).all()
    elif current_user.role == "org_admin":
        if contact_role == "platform_admin":
            from app.models import PlatformAdmin
            plat_admin = PlatformAdmin.query.first()
            plat_admin_id = plat_admin.id if plat_admin else 1
            messages = ChatMessage.query.filter(
                ((ChatMessage.sender_type == "org_admin") & (ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_type == "platform_admin")) |
                ((ChatMessage.sender_type == "platform_admin") & (ChatMessage.recipient_type == "org_admin") & (ChatMessage.recipient_id == current_user.id))
            ).order_by(ChatMessage.created_at.asc()).all()
        else:
            messages = ChatMessage.query.filter_by(
                organization_id=current_user.organization_id
            ).filter(
                ((ChatMessage.sender_type == "org_admin") & (ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_type == "worker") & (ChatMessage.recipient_id == contact_id)) |
                ((ChatMessage.sender_type == "worker") & (ChatMessage.sender_id == contact_id) & (ChatMessage.recipient_type == "org_admin") & (ChatMessage.recipient_id == current_user.id))
            ).order_by(ChatMessage.created_at.asc()).all()
    elif current_user.role == "worker":
        messages = ChatMessage.query.filter_by(
            organization_id=current_user.organization_id
        ).filter(
            ((ChatMessage.sender_type == "worker") & (ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_type == "org_admin") & (ChatMessage.recipient_id == contact_id)) |
            ((ChatMessage.sender_type == "org_admin") & (ChatMessage.sender_id == contact_id) & (ChatMessage.recipient_type == "worker") & (ChatMessage.recipient_id == current_user.id))
        ).order_by(ChatMessage.created_at.asc()).all()
        
    for m in messages:
        if m.recipient_type == ("platform_admin" if is_platform else current_user.role) and m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True
    db.session.commit()
    
    return jsonify({"messages": [m.to_dict() for m in messages]})


@api_bp.route("/chat/send", methods=["POST"])
@login_required
def send_chat_message():
    from app.models import ChatMessage, DashboardNotification
    data = request.get_json() or {}
    recipient_id = data.get("recipient_id")
    if recipient_id is not None:
        try:
            recipient_id = int(recipient_id)
        except (ValueError, TypeError):
            recipient_id = None
    recipient_role = data.get("recipient_role")
    msg_text = data.get("message", "").strip()
    
    if recipient_id is None or not recipient_role or not msg_text:
        return jsonify({"error": "Missing parameters"}), 400
        
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    sender_type = "platform_admin" if is_platform else current_user.role
    sender_id = current_user.id
    org_id = None if is_platform else current_user.organization_id
    
    if sender_type == "org_admin" and recipient_role == "platform_admin":
        from app.models import PlatformAdmin, PlatformNotification
        plat_admin = PlatformAdmin.query.first()
        r_id = plat_admin.id if plat_admin else 1
        
        msg = ChatMessage(
            sender_type=sender_type,
            sender_id=sender_id,
            recipient_type="platform_admin",
            recipient_id=r_id,
            organization_id=org_id,
            message=msg_text
        )
        db.session.add(msg)
        
        p_notif = PlatformNotification(
            organization_id=current_user.organization_id,
            type="support_query",
            title=f"Support Query: {current_user.organization.name}",
            message=msg_text,
            link="/platform"
        )
        db.session.add(p_notif)
        
        db_notif = DashboardNotification(
            platform_admin_id=r_id,
            type="chat",
            title=f"Support request from {current_user.organization.name}",
            message=msg_text,
            link="/platform"
        )
        db.session.add(db_notif)
        db.session.commit()
        return jsonify({"success": True, "message": msg.to_dict()})
        
    elif sender_type == "platform_admin" and recipient_role == "org_admin":
        msg = ChatMessage(
            sender_type=sender_type,
            sender_id=sender_id,
            recipient_type="org_admin",
            recipient_id=recipient_id,
            organization_id=None,
            message=msg_text
        )
        db.session.add(msg)
        
        from app.models import OrganizationUser
        org_admin_user = OrganizationUser.query.get(recipient_id)
        # Notification removed to prevent chat alerts in the bell icon
        db.session.commit()
        return jsonify({"success": True, "message": msg.to_dict()})
    else:
        msg = ChatMessage(
            sender_type=sender_type,
            sender_id=sender_id,
            recipient_type=recipient_role,
            recipient_id=recipient_id,
            organization_id=org_id,
            message=msg_text
        )
        db.session.add(msg)
        
        db.session.commit()
        return jsonify({"success": True, "message": msg.to_dict()})


@api_bp.route("/chat/edit", methods=["POST"])
@login_required
def edit_chat_message():
    from app.models import ChatMessage
    data = request.get_json() or {}
    message_id = data.get("message_id")
    new_text = data.get("message", "").strip()
    
    if not message_id or not new_text:
        return jsonify({"error": "Missing parameters"}), 400
        
    msg = ChatMessage.query.get(message_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404
        
    # Ensure current user is the sender of the message
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    expected_sender_type = "platform_admin" if is_platform else current_user.role
    
    if msg.sender_type != expected_sender_type or msg.sender_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
        
    if msg.is_deleted:
        return jsonify({"error": "Cannot edit a deleted message"}), 400
        
    msg.message = new_text
    msg.is_edited = True
    db.session.commit()
    
    return jsonify({"success": True, "message": msg.to_dict()})


@api_bp.route("/chat/delete", methods=["POST"])
@login_required
def delete_chat_message():
    from app.models import ChatMessage
    data = request.get_json() or {}
    message_id = data.get("message_id")
    
    if not message_id:
        return jsonify({"error": "Missing message_id"}), 400
        
    msg = ChatMessage.query.get(message_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404
        
    # Ensure current user is the sender of the message
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    expected_sender_type = "platform_admin" if is_platform else current_user.role
    
    if msg.sender_type != expected_sender_type or msg.sender_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
        
    msg.is_deleted = True
    msg.reactions = None
    db.session.commit()
    
    return jsonify({"success": True, "message": msg.to_dict()})


@api_bp.route("/chat/react", methods=["POST"])
@login_required
def react_chat_message():
    from app.models import ChatMessage
    import json
    data = request.get_json() or {}
    message_id = data.get("message_id")
    emoji = data.get("emoji")
    
    if not message_id:
        return jsonify({"error": "Missing message_id"}), 400
        
    msg = ChatMessage.query.get(message_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404
        
    if msg.is_deleted:
        return jsonify({"error": "Cannot react to a deleted message"}), 400
        
    # Get current user key for reactions dict (e.g. "org_admin_4" or "worker_2")
    is_platform = hasattr(current_user, "role") and current_user.role == "platform_owner"
    user_key = f"{'platform_admin' if is_platform else current_user.role}_{current_user.id}"
    
    reactions_dict = {}
    if msg.reactions:
        try:
            reactions_dict = json.loads(msg.reactions)
        except Exception:
            reactions_dict = {}
            
    if emoji:
        reactions_dict[user_key] = emoji
    else:
        reactions_dict.pop(user_key, None)
        
    msg.reactions = json.dumps(reactions_dict)
    db.session.commit()
    
    return jsonify({"success": True, "message": msg.to_dict()})


@api_bp.route("/onboarding/complete", methods=["POST"])
@login_required
def complete_onboarding():
    print(f"[DEBUG ONBOARDING] User: {current_user}, ID: {getattr(current_user, 'id', None)}, Role: {getattr(current_user, 'role', None)}")
    if hasattr(current_user, "onboarding_completed"):
        print(f"[DEBUG ONBOARDING] hasattr: True, current status: {current_user.onboarding_completed}")
        current_user.onboarding_completed = True
        db.session.commit()
        print(f"[DEBUG ONBOARDING] Committed. New status: {current_user.onboarding_completed}")
        return jsonify({"success": True})
    print(f"[DEBUG ONBOARDING] hasattr: False")
    return jsonify({"error": "User does not support onboarding"}), 400


@api_bp.route("/ai-assistant/ask", methods=["POST"])
@login_required
def ai_assistant_ask():
    data = request.get_json() or {}
    question = data.get("question", "").lower().strip()
    
    if not question:
        return jsonify({"answer": "<p>Please ask a question, and I will guide you!</p>"})
        
    answer_html = ""
    
    if "campaign" in question:
        answer_html = """
        <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
            <h6 style="color: #10b981; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-megaphone-fill"></i> Campaign Management Guide</h6>
            <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">CalltoConvey allows you to run high-converting Voice and WhatsApp fallback campaigns. Here is how you can set up a campaign:</p>
            <ol style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                <li>Navigate to the <strong>Campaigns</strong> dashboard using the sidebar.</li>
                <li>Click on the <strong>"Create Campaign"</strong> or <strong>"New Campaign"</strong> button in the top right.</li>
                <li>Configure the channels (select a Communication Gateway like Twilio or Hooman Labs voice agent).</li>
                <li>Import a list of contacts from a custom CRM Module or text group.</li>
                <li>Upload or select the dynamic call/SMS script template.</li>
                <li>Review all gateway costs and click <strong>"Launch Campaign"</strong>!</li>
            </ol>
            <a href="/org/campaigns" class="btn btn-sm" style="background: linear-gradient(135deg, #10b981, #059669); color: #fff; font-weight: 600; border-radius: 8px; padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.75rem; display: inline-block;"><i class="bi bi-arrow-right-short"></i> Go to Campaigns</a>
        </div>
        """
    elif "worker" in question or "add user" in question or "hire" in question:
        answer_html = """
        <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
            <h6 style="color: #3b82f6; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-people-fill"></i> Managing Workers</h6>
            <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">Workers are users who handle call dialing logs and review system events. To manage workers:</p>
            <ul style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                <li>Go to the <strong>Workers</strong> dashboard page.</li>
                <li>Click <strong>"Add Worker"</strong>.</li>
                <li>Enter their name, email, designation, and login password.</li>
                <li>Once added, workers can log in to their specialized premium workspace using their credentials to view tasks.</li>
            </ul>
            <a href="/org/workers" class="btn btn-sm" style="background: linear-gradient(135deg, #3b82f6, #2563eb); color: #fff; font-weight: 600; border-radius: 8px; padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.75rem; display: inline-block;"><i class="bi bi-arrow-right-short"></i> Go to Workers Space</a>
        </div>
        """
    elif "setting" in question or "gateway" in question or "number" in question or "twilio" in question:
        answer_html = """
        <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
            <h6 style="color: #f59e0b; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-gear-fill"></i> Gateways & Configuration</h6>
            <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">Set up communication integrations to allow automated workflows to reach your clients:</p>
            <ul style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                <li>Navigate to the <strong>Settings</strong> page via the sidebar.</li>
                <li>Click on <strong>"Communication Settings"</strong>.</li>
                <li>Enter your Twilio Account SID, Auth Token, or configure custom AI agent pipelines (Hindi, Tamil, English, etc.).</li>
                <li>Save the details to activate dynamic real-time communication modules immediately.</li>
            </ul>
            <a href="/org/profile" class="btn btn-sm" style="background: linear-gradient(135deg, #f59e0b, #d97706); color: #fff; font-weight: 600; border-radius: 8px; padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.75rem; display: inline-block;"><i class="bi bi-arrow-right-short"></i> Adjust Settings</a>
        </div>
        """
    elif "crm" in question or "module" in question or "field" in question:
        if getattr(current_user, 'role', '') == 'worker':
            answer_html = """
            <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
                <h6 style="color: #8b5cf6; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-grid-1x2-fill"></i> CRM Modules</h6>
                <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">As a Worker, you can access and manage data within the modules assigned to you:</p>
                <ul style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                    <li>Go to your <strong>Workspace</strong>.</li>
                    <li>Click on any assigned CRM Module to view, search, and edit records based on your permissions.</li>
                </ul>
                <a href="/worker/dashboard" class="btn btn-sm" style="background: linear-gradient(135deg, #8b5cf6, #7c3aed); color: #fff; font-weight: 600; border-radius: 8px; padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.75rem; display: inline-block;"><i class="bi bi-arrow-right-short"></i> Go to Workspace</a>
            </div>
            """
        else:
            answer_html = """
            <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
                <h6 style="color: #8b5cf6; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-grid-1x2-fill"></i> Creating CRM Modules</h6>
                <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">Customize your workspace with bespoke CRM modules, allowing dynamic customer structures:</p>
                <ul style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                    <li>Go to the main <strong>Dashboard</strong>.</li>
                    <li>Locate the <strong>"CRM Modules"</strong> pane.</li>
                    <li>Click <strong>"Create Custom Module"</strong>.</li>
                    <li>Add attributes (fields) like phone numbers, text keys, dates, and assign automated logic rules!</li>
                </ul>
                <a href="/org/dashboard" class="btn btn-sm" style="background: linear-gradient(135deg, #8b5cf6, #7c3aed); color: #fff; font-weight: 600; border-radius: 8px; padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.75rem; display: inline-block;"><i class="bi bi-arrow-right-short"></i> Go to CRM Dashboard</a>
            </div>
            """
    elif "billing" in question or "plan" in question or "invoice" in question or "pay" in question:
        if getattr(current_user, 'role', '') == 'worker':
            answer_html = """
            <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
                <p style="font-size: 0.85rem; margin-bottom: 0;">Billing and subscription management is handled by your Organization Administrator.</p>
            </div>
            """
        else:
            answer_html = """
            <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
                <h6 style="color: #ec4899; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-credit-card-fill"></i> Billing, Invoices & Checkout</h6>
                <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">Manage subscription packages, payments, and print invoices securely:</p>
                <ul style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                    <li>Click on **Subscriptions / Billing** in the sidebar navigation.</li>
                    <li>Browse available packages (Starter, Growth, premium enterprise plans) and select <strong>"Upgrade Plan"</strong>.</li>
                    <li>Under the payments portal, securely process payments via active gateways.</li>
                    <li>Navigate to the **Invoices** tab to view receipt lists or print formatted invoice sheets.</li>
                </ul>
                <a href="/org/browse-plans" class="btn btn-sm" style="background: linear-gradient(135deg, #ec4899, #db2777); color: #fff; font-weight: 600; border-radius: 8px; padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.75rem; display: inline-block;"><i class="bi bi-arrow-right-short"></i> Manage Billing</a>
            </div>
            """
    else:
        answer_html = """
        <div class="ai-card" style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1rem; color: #fff;">
            <h6 style="color: #a8a29e; font-weight: 700; margin-bottom: 0.5rem;"><i class="bi bi-robot"></i> CalltoConvey AI Support</h6>
            <p style="font-size: 0.85rem; margin-bottom: 0.5rem;">I am here to help you get the most out of CalltoConvey. Try asking about:</p>
            <ul style="font-size: 0.8rem; padding-left: 1.2rem; margin-bottom: 0.75rem;">
                <li><code>How do I create a campaign?</code></li>
                <li><code>How do I add a new worker?</code></li>
                <li><code>Where do I configure Twilio?</code></li>
                <li><code>How do I manage plans and payments?</code></li>
            </ul>
            <p style="font-size: 0.85rem; margin-bottom: 0;">Or feel free to raise a support request directly with Platform Care using the Customer Care widget in the bottom-right corner!</p>
        </div>
        """
        
    return jsonify({"answer": answer_html})


@api_bp.route("/helpdesk/create", methods=["POST"])
@login_required
def create_helpdesk_query():
    from app.models.helpdesk import HelpdeskQuery
    from app.models import DashboardNotification, PlatformNotification, PlatformAdmin
    
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400
        
    ticket_num = HelpdeskQuery.generate_ticket_number()
    query = HelpdeskQuery(
        ticket_number=ticket_num,
        user_type=current_user.role,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        message=message,
        status="Pending"
    )
    db.session.add(query)
    
    # Notify Platform Admins
    plat_admins = PlatformAdmin.query.all()
    for p_admin in plat_admins:
        db_notif = DashboardNotification(
            platform_admin_id=p_admin.id,
            type="chat",
            title=f"New Helpdesk Query {ticket_num}",
            message=f"Raised by {current_user.full_name or current_user.email} ({current_user.role.upper()}): {message[:100]}...",
            link="/platform/helpdesk"
        )
        db.session.add(db_notif)
        
    # Also add a PlatformNotification for auditing/logs
    p_notif = PlatformNotification(
        organization_id=current_user.organization_id,
        type="support_query",
        title=f"Helpdesk Query {ticket_num}",
        message=message,
        link="/platform/helpdesk"
    )
    db.session.add(p_notif)
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Query raised successfully",
        "query": query.to_dict()
    })


@api_bp.route("/helpdesk/list", methods=["GET"])
@login_required
def list_helpdesk_queries():
    from app.models.helpdesk import HelpdeskQuery
    queries = HelpdeskQuery.query.filter_by(
        user_id=current_user.id,
        organization_id=current_user.organization_id
    ).order_by(HelpdeskQuery.created_at.desc()).all()
    
    return jsonify({
        "queries": [q.to_dict() for q in queries]
    })


@api_bp.route("/api/upi/submit-payment", methods=["POST"])
@login_required
def submit_upi_payment():
    from app.models.platform import PaymentGateway, PaymentMethod, Plan
    from app.models.payment_verification import PaymentVerification
    from werkzeug.utils import secure_filename
    from flask import current_app
    from datetime import datetime
    import os
    import uuid
    import json
    import decimal

    # 1. Retrieve and validate fields
    plan_id = request.form.get("plan_id")
    campaign_id = request.form.get("campaign_id")
    gateway_id = request.form.get("gateway_id")
    transaction_id = request.form.get("transaction_id", "").strip()
    customer_upi_id = request.form.get("customer_upi_id", "").strip()
    additional_notes = request.form.get("additional_notes", "").strip()
    ref_num = request.form.get("ref_num", "").strip()
    amount_str = request.form.get("amount")

    if not gateway_id or not transaction_id:
        return jsonify({"error": "Missing required transaction fields"}), 400

    plan = None
    campaign = None
    if plan_id:
        plan = Plan.query.get(plan_id)
        if not plan:
            return jsonify({"error": "Plan not found"}), 400
        order_id = f"SUB-{plan_id}"
        org_id = current_user.organization_id
    elif campaign_id:
        from app.models import Campaign
        from app.models.campaign_express import CampaignExpressPayment
        campaign = Campaign.query.get(campaign_id)
        if not campaign:
            return jsonify({"error": "Campaign not found"}), 400
        order_id = f"CE-{campaign_id}"
        org_id = campaign.organization_id or (current_user.organization_id if hasattr(current_user, "organization_id") else None)
    else:
        return jsonify({"error": "Missing required plan_id or campaign_id"}), 400

    gateway = PaymentGateway.query.get(gateway_id)
    if not gateway or gateway.provider != "dynamic_upi":
        return jsonify({"error": "Invalid payment gateway selected"}), 400

    # 2. Block Duplicate Transaction IDs
    existing = PaymentVerification.query.filter_by(transaction_id=transaction_id).first()
    if existing:
        return jsonify({"error": "This Transaction ID / UTR has already been submitted for verification."}), 400

    # 3. Handle File Upload (Screenshot)
    if "screenshot" not in request.files:
        return jsonify({"error": "Screenshot upload is required"}), 400

    file = request.files["screenshot"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Read config from PaymentMethod
    upi_method = PaymentMethod.query.filter_by(type="dynamic_upi").first()
    upi_config = {}
    if upi_method:
        try:
            upi_config = json.loads(upi_method.instructions)
        except Exception:
            pass

    allowed_exts = upi_config.get("accepted_file_types", "jpg,jpeg,png,webp,pdf").split(",")
    max_mb = float(upi_config.get("max_upload_size", "10"))
    max_bytes = max_mb * 1024 * 1024

    # Validate file type
    file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_ext not in allowed_exts:
        return jsonify({"error": f"Invalid file format. Allowed types: {', '.join(allowed_exts).upper()}"}), 400

    # Validate file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset pointer to beginning
    if file_size > max_bytes:
        return jsonify({"error": f"File size exceeds the configured {max_mb}MB limit."}), 400

    # Save file securely
    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "payment_screenshots")
    os.makedirs(upload_dir, exist_ok=True)
    
    unique_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file_path = os.path.join(upload_dir, unique_filename)
    file.save(file_path)

    # Relative path to store in database
    db_relative_path = f"uploads/payment_screenshots/{unique_filename}"

    # 4. Gather Device & IP Information
    ip_address = request.remote_addr
    device_info = request.headers.get("User-Agent", "Unknown Device")

    # 5. Create PaymentVerification Record
    try:
        if amount_str:
            amount = decimal.Decimal(amount_str)
        elif plan:
            amount = decimal.Decimal(plan.price) * decimal.Decimal("1.18")
        elif campaign:
            payment_record = CampaignExpressPayment.query.filter_by(
                campaign_id=campaign_id, status="pending"
            ).order_by(CampaignExpressPayment.created_at.desc()).first()
            if not payment_record:
                return jsonify({"error": "No pending campaign payment found"}), 400
            amount = payment_record.amount
    except Exception:
        amount = decimal.Decimal("0.00")

    # Audit Log initialization
    audit_log = [{
        "timestamp": datetime.utcnow().isoformat(),
        "action": "submitted",
        "user_email": current_user.email,
        "ip_address": ip_address,
        "details": f"Manual payment submitted for verification. Ref: {ref_num}"
    }]

    verification = PaymentVerification(
        order_id=order_id,
        organization_id=org_id,
        amount=amount,
        generated_upi_id=upi_config.get("upi_id", "merchant@upi"),
        transaction_id=transaction_id,
        screenshot_path=db_relative_path,
        customer_upi_id=customer_upi_id,
        status="pending",
        remarks=additional_notes,
        ip_address=ip_address,
        device_info=device_info,
        audit_log=audit_log
    )
    db.session.add(verification)
    db.session.flush() # Populate verification.id

    # 6. Create corresponding Payment record
    if plan:
        from app.models.organization import Payment
        payment = Payment(
            organization_id=org_id,
            amount=amount,
            status="pending_verification",
            gateway_id=gateway.id,
            gateway_name=gateway.name,
            gateway_provider=gateway.provider,
            gateway_mode=gateway.deployment_mode,
            transaction_id=transaction_id,
            meta={
                "verification_id": verification.id,
                "ref_num": ref_num,
                "notes": additional_notes
            }
        )
        db.session.add(payment)
    elif campaign:
        payment_record = CampaignExpressPayment.query.filter_by(
            campaign_id=campaign_id, status="pending"
        ).order_by(CampaignExpressPayment.created_at.desc()).first()
        if payment_record:
            payment_record.status = "pending_verification"
            payment_record.transaction_id = transaction_id
            payment_record.payment_ref = ref_num
            payment_record.gateway_id = gateway.id
            payment_record.gateway_name = gateway.name
            payment_record.gateway_provider = gateway.provider
            payment_record.gateway_mode = gateway.deployment_mode
            payment_record.meta = {
                "verification_id": verification.id,
                "notes": additional_notes
            }

    db.session.commit()

    # 7. Notify Platform Admins
    from app.models.platform import PlatformAdmin, PlatformNotification, DashboardNotification
    plat_admins = PlatformAdmin.query.all()
    for p_admin in plat_admins:
        db_notif = DashboardNotification(
            platform_admin_id=p_admin.id,
            type="payment",
            title="New UPI Payment Submitted",
            message=f"New payment verification request with UTR {transaction_id} was submitted.",
            link="/platform/payment-verifications"
        )
        db.session.add(db_notif)

    p_notif = PlatformNotification(
        organization_id=org_id,
        type="payment_verification",
        title="UPI Payment Verification Required",
        message=f"UTR: {transaction_id}, Amount: ₹{amount}. Manual review required.",
        link="/platform/payment-verifications"
    )
    db.session.add(p_notif)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Payment details submitted successfully for manual verification.",
        "verification_id": verification.id
    })



@api_bp.route('/v1/modules/<int:module_id>/records', methods=['GET'])
@login_required
def get_module_records(module_id):
    from app.models.modules import Module, ModuleRecord
    
    # Verify module belongs to user's org
    module = db.get_or_404(Module, module_id)
    if hasattr(current_user, 'organization_id') and module.organization_id != current_user.organization_id:
        return jsonify({'error': 'Unauthorized'}), 403
        
    records = ModuleRecord.query.filter_by(module_id=module_id).order_by(ModuleRecord.created_at.desc()).all()
    
    data = []
    for r in records:
        record_data = r.named_values
        record_data['id'] = r.id
        record_data['created_at'] = r.created_at.isoformat()
        data.append(record_data)
        
    return jsonify({
        'module_name': module.name,
        'records': data
    })
