from datetime import datetime
import calendar
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import (
    PlatformAdmin,
    Organization,
    CommunicationNumber,
    Subscription,
    Payment,
    Plan,
    PaymentMethod,
    ChangeRequest,
    OrganizationUser,
    PlatformSecurity,
    PlatformNotification,
    DeliveryLog,
    Campaign,
    Script,
    Contact,
    ContactGroup,
    Module,
)
from app.models.campaign_express import CampaignExpressPayment
from app.core.decorators import platform_required
from app.config import Config

super_admin_bp = Blueprint(
    "super_admin", __name__, template_folder="templates"
)


@super_admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # --- Brute Force Protection ---
        from app.security.auth_protection import BruteForceProtection

        locked, lock_msg = BruteForceProtection.is_locked_out(email)
        if locked:
            flash(lock_msg, "danger")
            return render_template("auth/platform_login.html")

        sec_settings = PlatformSecurity.get_settings()

        # If trying to login as default admin, check if it's enabled
        if email == Config.DEFAULT_ADMIN_EMAIL:
            if not sec_settings.default_admin_enabled:
                flash("Default administrative access is currently disabled.", "danger")
                return render_template("auth/platform_login.html")

        admin = PlatformAdmin.query.filter_by(email=email).first()
        if admin and admin.check_password(password):
            # Check if MFA is enabled
            from app.security.mfa import MFAService
            from flask import session

            user_type = "platform_admin"
            config = MFAService.get_mfa_config(admin.id, user_type)

            if config.is_enabled:
                session["pre_mfa_user_id"] = admin.id
                session["pre_mfa_user_type"] = user_type
                session["pre_mfa_remember"] = "remember" in request.form

                # Generate and send OTP
                success, msg = MFAService.generate_and_send_otp(
                    admin.id, user_type, method=config.mfa_type
                )
                if success:
                    flash("Verification code sent.", "info")
                    return redirect(url_for("security.verify_otp"))
                else:
                    flash(f"Error sending verification code: {msg}", "danger")
                    return render_template("auth/platform_login.html")
            else:
                from app.security.session_manager import SessionManager
                from urllib.parse import urlparse

                login_user(admin, remember="remember" in request.form)
                SessionManager.regenerate_session()
                SessionManager.track_session(admin.id, user_type)
                
                next_page = request.args.get("next")
                if next_page:
                    parsed = urlparse(next_page)
                    if parsed.netloc == "" or parsed.netloc == request.host:
                        return redirect(next_page)
                return redirect(url_for("super_admin.dashboard"))
        BruteForceProtection.log_failed_attempt(identifier=email)
        flash("Invalid credentials", "danger")
    return render_template("auth/platform_login.html")


@super_admin_bp.route("/")
@platform_required
def dashboard():
    # Platform owner only
    orgs = Organization.query.all()
    numbers = CommunicationNumber.query.filter_by(
        is_platform_owned=False, approved=False
    ).all()

    # System Overview Stats
    total_orgs = len(orgs)

    # Calculate revenue (completed payments from Organizations + Campaign Express)
    org_revenue = (
        db.session.query(func.sum(Payment.amount))
        .filter(Payment.status == "completed")
        .scalar()
    )
    
    ce_revenue = (
        db.session.query(func.sum(CampaignExpressPayment.amount))
        .filter(CampaignExpressPayment.status == "completed")
        .scalar()
    )
    
    total_revenue = (float(org_revenue) if org_revenue else 0.0) + (float(ce_revenue) if ce_revenue else 0.0)

    # Active Subscriptions
    active_subs = Subscription.query.filter_by(status="active").count()

    # NEW: Approved organizations without active plans
    # We find orgs with status='active' whose IDs are not in Subscription table with status='active'
    subbed_org_ids = [
        s.organization_id for s in Subscription.query.filter_by(status="active").all()
    ]
    pending_subscription_orgs = Organization.query.filter(
        Organization.status == "active", ~Organization.id.in_(subbed_org_ids)
    ).all()

    # Recent Payments
    recent_payments = Payment.query.order_by(Payment.id.desc()).limit(4).all()

    # Notifications
    from app.common.notifications.service import (
        get_recent_notifications,
        get_unread_count,
    )

    notifications = get_recent_notifications(10)
    unread_notifs = get_unread_count()

    growth_categories = []
    growth_data = []

    now = datetime.utcnow()
    for i in range(5, -1, -1):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12
            y -= 1

        start_of_month = datetime(y, m, 1)
        _, last_day = calendar.monthrange(y, m)
        end_of_month = datetime(y, m, last_day, 23, 59, 59)

        month_revenue = (
            db.session.query(func.sum(Payment.amount))
            .filter(Payment.status == "completed")
            .filter(Payment.created_at >= start_of_month)
            .filter(Payment.created_at <= end_of_month)
            .scalar()
        )
        if month_revenue is None:
            month_revenue = 0.0

        month_abbr = calendar.month_abbr[m]
        growth_categories.append(month_abbr)
        growth_data.append(float(month_revenue))

    return render_template(
        "platform/dashboard.html",
        orgs=orgs,
        numbers=numbers,
        total_orgs=total_orgs,
        total_revenue=total_revenue,
        active_subs=active_subs,
        pending_subscription_orgs=pending_subscription_orgs,
        recent_payments=recent_payments,
        notifications=notifications,
        unread_notifs=unread_notifs,
        growth_categories=growth_categories,
        growth_data=growth_data,
    )

@super_admin_bp.route("/ce/dashboard")
@platform_required
def ce_dashboard():
    from app.models.campaign_express import CampaignExpressUser, CampaignExpressPayment
    from app.models.ce_number_pool import CeNumberPool
    from app.models import Campaign
    
    total_ce_users = CampaignExpressUser.query.count()
    running_ce_campaigns = Campaign.query.filter(Campaign.campaign_express_user_id.isnot(None), Campaign.status == 'running').count()
    total_ce_revenue = db.session.query(func.sum(CampaignExpressPayment.amount)).filter(CampaignExpressPayment.status == "completed").scalar() or 0.0
    
    ce_numbers_all = CeNumberPool.query.all()
    ce_numbers_total = len(ce_numbers_all)
    ce_numbers_active = sum(1 for n in ce_numbers_all if n.active_campaigns_count and n.active_campaigns_count > 0)

    return render_template(
        "platform/ce/ce_dashboard.html",
        total_ce_users=total_ce_users,
        running_ce_campaigns=running_ce_campaigns,
        total_ce_revenue=total_ce_revenue,
        ce_numbers_active=ce_numbers_active,
        ce_numbers_total=ce_numbers_total
    )


@super_admin_bp.route("/notifications")
@platform_required
def notifications():
    from app.common.notifications.service import (
        get_recent_notifications,
        get_unread_count,
    )
    from app.models.helpdesk import HelpdeskQuery
    from datetime import datetime

    # Fetch more for the full page
    all_notifs = get_recent_notifications(50)

    # Calculate real-time resolved helpdesk queries today in local IST time (matching the user's timezone)
    from datetime import timedelta
    IST_OFFSET = timedelta(hours=5, minutes=30)
    now_ist = datetime.utcnow() + IST_OFFSET
    today_midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_midnight_ist - IST_OFFSET

    resolved_today_count = HelpdeskQuery.query.filter(
        HelpdeskQuery.status == "Resolved",
        HelpdeskQuery.resolved_at >= today_start
    ).count()

    return render_template(
        "platform/notifications.html", 
        notifications=all_notifs,
        resolved_today_count=resolved_today_count
    )


@super_admin_bp.route("/notifications/<int:nid>/read", methods=["POST"])
@platform_required
def mark_notification_read(nid):
    n = db.get_or_404(PlatformNotification, nid)
    n.is_read = True
    db.session.commit()
    flash("Notification marked as read.", "success")
    return redirect(url_for("super_admin.notifications"))


@super_admin_bp.route("/notifications/read-all", methods=["POST"])
@platform_required
def mark_all_notifications_read():
    PlatformNotification.query.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("super_admin.notifications"))


@super_admin_bp.route("/orgs/<int:org_id>")
@platform_required
def view_org_detail(org_id):
    """
    Detailed view for an organization showing registration profile
    and live operational metrics.
    """
    org = db.get_or_404(Organization, org_id)
    subscription = Subscription.query.filter_by(organization_id=org_id).first()

    # 1. Registration & Profile Data
    primary_admin = OrganizationUser.query.filter_by(
        organization_id=org_id, role="org_admin"
    ).first()

    # 2. Worker Count
    worker_count = OrganizationUser.query.filter(
        OrganizationUser.organization_id == org_id, OrganizationUser.role != "org_admin"
    ).count()

    # 3. Communication Stats
    org_campaign_ids = [
        c.id for c in Campaign.query.filter_by(organization_id=org_id).all()
    ]

    msg_sent = 0
    calls_made = 0

    if org_campaign_ids:
        msg_sent = DeliveryLog.query.filter(
            DeliveryLog.campaign_id.in_(org_campaign_ids),
            DeliveryLog.channel.in_(["whatsapp_text", "whatsapp_voice"]),
        ).count()

        calls_made = DeliveryLog.query.filter(
            DeliveryLog.campaign_id.in_(org_campaign_ids), DeliveryLog.channel == "call"
        ).count()

    # 4. Subscription & Billing
    subscription = Subscription.query.filter_by(organization_id=org_id).first()
    payments = (
        Payment.query.filter_by(organization_id=org_id)
        .order_by(Payment.id.desc())
        .all()
    )

    # 5. Pending Number Requests
    pending_request = ChangeRequest.query.filter_by(
        organization_id=org_id, field_name="number_request", status="pending"
    ).first()

    # 6. Available plans
    plans = Plan.query.order_by(Plan.price.asc()).all()

    return render_template(
        "platform/org_detail.html",
        org=org,
        admin=primary_admin,
        worker_count=worker_count,
        msg_sent=msg_sent,
        calls_made=calls_made,
        subscription=subscription,
        payments=payments,
        pending_request=pending_request,
        plans=plans,
    )


@super_admin_bp.route("/orgs/<int:org_id>/edit-profile", methods=["POST"])
@platform_required
def edit_org_profile(org_id):
    org = db.get_or_404(Organization, org_id)
    
    org.name = request.form.get("name")
    org.org_type = request.form.get("org_type")
    org.industry = request.form.get("industry")
    org.support_email = request.form.get("support_email")
    org.support_phone = request.form.get("support_phone")
    org.country = request.form.get("country")
    org.language_preference = request.form.get("language_preference")
    org.office_address = request.form.get("office_address")
    
    # Also update admin email
    admin_email = request.form.get("admin_email")
    if admin_email:
        admin = OrganizationUser.query.filter_by(
            organization_id=org_id, role="org_admin"
        ).first()
        if admin:
            existing = OrganizationUser.query.filter_by(
                email=admin_email, organization_id=org_id
            ).first()
            if existing and existing.id != admin.id:
                flash("Error: Email is already used by another user in this organization.", "danger")
                return redirect(url_for("super_admin.view_org_detail", org_id=org_id))
            admin.email = admin_email
            
    db.session.commit()
    flash("Organization profile updated successfully.", "success")
    return redirect(url_for("super_admin.view_org_detail", org_id=org_id))


@super_admin_bp.route("/orgs/<int:org_id>/reset-password", methods=["POST"])
@platform_required
def reset_org_password(org_id):
    from werkzeug.security import generate_password_hash
    org = db.get_or_404(Organization, org_id)
    admin = OrganizationUser.query.filter_by(
        organization_id=org_id, role="org_admin"
    ).first()
    
    if not admin:
        flash("Error: Primary administrator account not found for this organization.", "danger")
        return redirect(url_for("super_admin.view_org_detail", org_id=org_id))
        
    new_password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")
    
    if not new_password or len(new_password) < 6:
        flash("Error: Password must be at least 6 characters long.", "danger")
        return redirect(url_for("super_admin.view_org_detail", org_id=org_id))
        
    if new_password != confirm_password:
        flash("Error: Passwords do not match.", "danger")
        return redirect(url_for("super_admin.view_org_detail", org_id=org_id))
        
    admin.password_hash = generate_password_hash(new_password)
    db.session.commit()
    
    flash(f"Password for {admin.email} has been successfully reset.", "success")
    return redirect(url_for("super_admin.view_org_detail", org_id=org_id))


@super_admin_bp.route("/orgs/<int:org_id>/approve", methods=["POST"])
@platform_required
def approve_org(org_id):
    org = db.get_or_404(Organization, org_id)
    org.status = "active"
    org.is_verified = True

    # Mark related notifications as read
    PlatformNotification.query.filter_by(
        organization_id=org_id, type="new_organization", is_read=False
    ).update({"is_read": True})

    db.session.commit()
    flash(f"Organization {org.name} has been approved and activated.", "success")
    return redirect(url_for("super_admin.pending_changes"))


@super_admin_bp.route("/orgs/<int:org_id>/reject", methods=["POST"])
@platform_required
def reject_org(org_id):
    org = db.get_or_404(Organization, org_id)
    reason = request.form.get("reason", "")

    org.status = "rejected"
    org.is_verified = False

    # Store rejection reason in description field
    if reason:
        org.description = f"Rejected: {reason}"

    # Mark related notifications as read
    PlatformNotification.query.filter_by(
        organization_id=org_id, type="new_organization", is_read=False
    ).update({"is_read": True})

    db.session.commit()
    flash(f"Organization {org.name} has been rejected.", "warning")
    return redirect(url_for("super_admin.pending_changes"))


@super_admin_bp.route("/orgs/<int:org_id>/suspend", methods=["POST"])
@platform_required
def suspend_org(org_id):
    org = db.get_or_404(Organization, org_id)
    org.status = "suspended"
    org.is_verified = False
    db.session.commit()
    flash(f"Organization {org.name} has been suspended.", "warning")
    return redirect(url_for("super_admin.view_org_detail", org_id=org_id))


@super_admin_bp.route("/orgs/<int:org_id>/delete", methods=["POST"])
@platform_required
def delete_org(org_id):
    org = db.get_or_404(Organization, org_id)
    org_name = org.name

    try:
        # Delete all associated data in correct order
        Campaign.query.filter_by(organization_id=org_id).delete()
        ContactGroup.query.filter_by(organization_id=org_id).delete()
        Contact.query.filter_by(organization_id=org_id).delete()
        Module.query.filter_by(organization_id=org_id).delete()
        Subscription.query.filter_by(organization_id=org_id).delete()
        Payment.query.filter_by(organization_id=org_id).delete()
        CommunicationNumber.query.filter_by(organization_id=org_id).delete()
        ChangeRequest.query.filter_by(organization_id=org_id).delete()
        PlatformNotification.query.filter_by(organization_id=org_id).delete()
        OrganizationUser.query.filter_by(organization_id=org_id).delete()

        db.session.delete(org)
        db.session.commit()

        flash(
            f'Organization "{org_name}" and all associated data have been permanently deleted.',
            "success",
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting organization: {str(e)}", "danger")

    return redirect(url_for("super_admin.dashboard"))


@super_admin_bp.route("/orgs/<int:org_id>/toggle_subscription", methods=["POST"])
@platform_required
def toggle_subscription_status(org_id):
    sub = Subscription.query.filter_by(organization_id=org_id).first()
    if not sub:
        sub = Subscription(organization_id=org_id, status="active")
        db.session.add(sub)

    sub.status = "inactive" if sub.status == "active" else "active"
    db.session.commit()

    flash(
        f"Subscription status for organization updated to {sub.status.upper()}",
        "success",
    )
    return redirect(url_for("super_admin.view_org_detail", org_id=org_id))


@super_admin_bp.route("/orgs/<int:org_id>/update_subscription", methods=["POST"])
@platform_required
def update_subscription(org_id):
    plan = request.form.get("plan")
    expires_at_str = request.form.get("expires_at")
    status = request.form.get("status")
    billing_interval = request.form.get("billing_interval", "monthly")

    sub = Subscription.query.filter_by(organization_id=org_id).first()
    if not sub:
        sub = Subscription(organization_id=org_id)
        db.session.add(sub)

    sub.plan = plan
    sub.status = status
    sub.billing_interval = billing_interval

    if expires_at_str:
        try:
            sub.expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid date format. Use YYYY-MM-DD.", "danger")
            return redirect(url_for("super_admin.view_org_detail", org_id=org_id))
    else:
        sub.expires_at = None

    db.session.commit()
    flash("Subscription updated successfully.", "success")
    return redirect(url_for("super_admin.view_org_detail", org_id=org_id))


@super_admin_bp.route("/orgs/<int:org_id>/configure_twilio", methods=["POST"])
@platform_required
def configure_twilio(org_id):
    org = db.get_or_404(Organization, org_id)

    # Get form data
    voice_sid = request.form.get("voice_sid")
    voice_token = request.form.get("voice_token")
    voice_number = request.form.get("voice_number")

    wa_sid = request.form.get("wa_sid")
    wa_token = request.form.get("wa_token")
    wa_number = request.form.get("wa_number")

    hooman_number = request.form.get("hooman_number")
    hooman_api_key = request.form.get("hooman_api_key")

    # Update Config
    config = org.twilio_config or {}

    if voice_sid and voice_token and voice_number:
        config["voice"] = {
            "sid": voice_sid,
            "token": voice_token,
            "number": voice_number,
        }
        # Clear pending voice request
        req = ChangeRequest.query.filter_by(
            organization_id=org_id,
            field_name="number_request",
            status="pending",
            new_value="voice",
        ).first()
        if req:
            req.status = "approved"

        exists = CommunicationNumber.query.filter_by(
            organization_id=org_id, number=voice_number
        ).first()
        if not exists:
            cn = CommunicationNumber(
                organization_id=org_id,
                number=voice_number,
                channel_type="voice",
                approved=True,
                active=True,
                is_platform_owned=False,
            )
            db.session.add(cn)

    if wa_sid and wa_token and wa_number:
        config["whatsapp"] = {"sid": wa_sid, "token": wa_token, "number": wa_number}
        # Clear pending whatsapp request
        req = ChangeRequest.query.filter_by(
            organization_id=org_id,
            field_name="number_request",
            status="pending",
            new_value="whatsapp",
        ).first()
        if req:
            req.status = "approved"

        exists = CommunicationNumber.query.filter_by(
            organization_id=org_id, number=wa_number
        ).first()
        if not exists:
            cn = CommunicationNumber(
                organization_id=org_id,
                number=wa_number,
                channel_type="whatsapp",
                approved=True,
                active=True,
                is_platform_owned=False,
            )
            db.session.add(cn)

    # Hooman Labs Config Save Logic
    updated_hooman = False
    if hooman_api_key or hooman_number:
        hooman_cfg = org.hooman_config or {}
        if not isinstance(hooman_cfg, dict):
            hooman_cfg = {}

        if hooman_api_key:
            hooman_cfg["api_key"] = hooman_api_key
            updated_hooman = True
        if hooman_number:
            hooman_cfg["number"] = hooman_number
            updated_hooman = True

        if updated_hooman:
            org.hooman_config = hooman_cfg
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(org, "hooman_config")

            # Clear pending hooman_voice request
            req = ChangeRequest.query.filter_by(
                organization_id=org_id,
                field_name="number_request",
                status="pending",
                new_value="hooman_voice",
            ).first()
            if req:
                req.status = "approved"

            target_num = hooman_number if hooman_number else hooman_cfg.get("number")
            if target_num:
                exists = CommunicationNumber.query.filter_by(
                    organization_id=org_id,
                    number=target_num,
                ).first()
                if not exists:
                    cn = CommunicationNumber(
                        organization_id=org_id,
                        number=target_num,
                        channel_type="hooman_voice",
                        approved=True,
                        active=True,
                        is_platform_owned=False,
                    )
                    db.session.add(cn)

    # Force update Twilio JSON column
    org.twilio_config = config
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(org, "twilio_config")

    try:
        db.session.commit()
        msg = "Communication settings updated successfully"
        if updated_hooman:
            msg += " (including Hooman Labs config)"
        flash(msg, "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error saving configuration: {str(e)}", "danger")

    return redirect(url_for("super_admin.view_org_detail", org_id=org_id))


@super_admin_bp.route("/numbers/approve/<int:nid>", methods=["POST"])
@platform_required
def approve_number(nid):
    num = db.get_or_404(CommunicationNumber, nid)
    num.approved = True
    db.session.commit()
    flash("Number approved", "success")
    return redirect(url_for("super_admin.dashboard"))


@super_admin_bp.route("/settings/plans", methods=["GET", "POST"])
@platform_required
def manage_plans():
    if request.method == "POST":
        name = request.form.get("name")
        price = request.form.get("price")
        billing_interval = request.form.get("billing_interval", "monthly")
        description = request.form.get("description")
        features_str = request.form.get("features")
        features = [f.strip() for f in features_str.split(",")] if features_str else []

        plan_id = request.form.get("plan_id")
        if plan_id:
            plan = db.session.get(Plan, plan_id)
            if plan:
                plan.name = name
                plan.price = price
                plan.billing_interval = billing_interval
                plan.description = description
                plan.features = features
                flash(f"Plan {name} updated", "success")
        else:
            plan = Plan(
                name=name,
                price=price,
                billing_interval=billing_interval,
                description=description,
                features=features,
            )
            db.session.add(plan)
            flash(f"Plan {name} created successfully", "success")

        db.session.commit()
        return redirect(url_for("super_admin.manage_plans"))

    plans = Plan.query.order_by(Plan.price.asc()).all()

    # KPI data for the premium dashboard
    lowest_price = min(p.price for p in plans) if plans else 0
    highest_price = max(p.price for p in plans) if plans else 0
    billing_types = len(set(p.billing_interval for p in plans)) if plans else 0

    return render_template(
        "platform/settings_plans.html",
        plans=plans,
        lowest_price=lowest_price,
        highest_price=highest_price,
        billing_types=billing_types,
    )


@super_admin_bp.route("/settings/plans/delete/<int:plan_id>", methods=["POST"])
@platform_required
def delete_plan(plan_id):
    plan = db.get_or_404(Plan, plan_id)
    db.session.delete(plan)
    db.session.commit()
    flash(f"Plan {plan.name} deleted", "info")
    return redirect(url_for("super_admin.manage_plans"))


@super_admin_bp.route("/settings/payments", methods=["GET", "POST"])
@platform_required
def manage_payments():
    if request.method == "POST":
        name = request.form.get("name")
        method_type = request.form.get("type", "manual")
        instructions = request.form.get("instructions")
        is_active = request.form.get("is_active") == "on"

        method_id = request.form.get("method_id")
        if method_id:
            pm = db.session.get(PaymentMethod, method_id)
            if pm:
                pm.name = name
                pm.type = method_type
                pm.instructions = instructions
                pm.is_active = is_active
                flash(f"Payment method {name} updated", "success")
        else:
            pm = PaymentMethod(name=name, type=method_type, instructions=instructions, is_active=is_active)
            db.session.add(pm)
            flash(f"Payment method {name} added", "success")

        # Synchronize dynamic_upi gateway active state
        if method_type == "dynamic_upi":
            from app.models.platform import PaymentGateway
            gw = PaymentGateway.query.filter_by(provider="dynamic_upi").first()
            if gw:
                gw.active = is_active
            else:
                gw = PaymentGateway(
                    name="Dynamic UPI Payment",
                    provider="dynamic_upi",
                    gateway_type="manual",
                    active=is_active,
                    priority=2
                )
                db.session.add(gw)

        db.session.commit()
        return redirect(url_for("super_admin.manage_payments"))

    methods = PaymentMethod.query.all()

    # === REAL-TIME PAYMENT DATA ===
    from datetime import timedelta
    from decimal import Decimal

    now = datetime.utcnow()

    # Total completed payments count
    total_payments = Payment.query.filter_by(status="completed").count()

    # Total revenue (all time)
    total_revenue_raw = (
        db.session.query(func.sum(Payment.amount))
        .filter(Payment.status == "completed")
        .scalar()
    )
    total_revenue = float(total_revenue_raw) if total_revenue_raw else 0.0

    # Failed payments count
    failed_payments = Payment.query.filter(
        Payment.status.in_(["failed", "error"])
    ).count()

    # Success rate
    all_payments_count = Payment.query.count()
    if all_payments_count > 0:
        success_rate = round((total_payments / all_payments_count) * 100, 1)
    else:
        success_rate = 100.0

    # Monthly collections (current month)
    first_of_month = datetime(now.year, now.month, 1)
    monthly_revenue_raw = (
        db.session.query(func.sum(Payment.amount))
        .filter(Payment.status == "completed")
        .filter(Payment.created_at >= first_of_month)
        .scalar()
    )
    monthly_revenue = float(monthly_revenue_raw) if monthly_revenue_raw else 0.0

    # Previous month collections for trend comparison
    if now.month == 1:
        prev_month_start = datetime(now.year - 1, 12, 1)
        prev_month_end = datetime(now.year, 1, 1)
    else:
        prev_month_start = datetime(now.year, now.month - 1, 1)
        prev_month_end = first_of_month
    prev_monthly_raw = (
        db.session.query(func.sum(Payment.amount))
        .filter(Payment.status == "completed")
        .filter(Payment.created_at >= prev_month_start)
        .filter(Payment.created_at < prev_month_end)
        .scalar()
    )
    prev_monthly = float(prev_monthly_raw) if prev_monthly_raw else 0.0
    if prev_monthly > 0:
        monthly_growth = round(((monthly_revenue - prev_monthly) / prev_monthly) * 100, 1)
    else:
        monthly_growth = 0.0

    # Daily revenue trend (last 14 days)
    revenue_labels = []
    revenue_data = []
    for i in range(13, -1, -1):
        day = now - timedelta(days=i)
        day_start = datetime(day.year, day.month, day.day)
        day_end = day_start + timedelta(days=1)

        day_rev_raw = (
            db.session.query(func.sum(Payment.amount))
            .filter(Payment.status == "completed")
            .filter(Payment.created_at >= day_start)
            .filter(Payment.created_at < day_end)
            .scalar()
        )
        revenue_labels.append(day.strftime("%d %b"))
        revenue_data.append(float(day_rev_raw) if day_rev_raw else 0)

    # Payment method usage breakdown (from payment meta)
    all_completed = Payment.query.filter_by(status="completed").all()
    method_counts = {}
    for p in all_completed:
        method_name = "Other"
        if p.meta and isinstance(p.meta, dict):
            method_name = p.meta.get("method", p.meta.get("plan_name", "Other"))
        method_counts[method_name] = method_counts.get(method_name, 0) + 1

    usage_labels = list(method_counts.keys()) if method_counts else ["No data"]
    usage_series = list(method_counts.values()) if method_counts else [1]

    # Recent payments for billing log
    recent_payments = (
        Payment.query.order_by(Payment.created_at.desc()).limit(10).all()
    )

    return render_template(
        "platform/settings_payments.html",
        methods=methods,
        total_payments=total_payments,
        total_revenue=total_revenue,
        success_rate=success_rate,
        monthly_revenue=monthly_revenue,
        monthly_growth=monthly_growth,
        revenue_labels=revenue_labels,
        revenue_data=revenue_data,
        usage_labels=usage_labels,
        usage_series=usage_series,
        recent_payments=recent_payments,
    )


@super_admin_bp.route("/settings/payments/delete/<int:method_id>", methods=["POST"])
@platform_required
def delete_payment_method(method_id):
    pm = db.get_or_404(PaymentMethod, method_id)
    db.session.delete(pm)
    db.session.commit()
    flash(f"Payment method {pm.name} removed", "info")
    return redirect(url_for("super_admin.manage_payments"))


@super_admin_bp.route("/payment-verifications", methods=["GET"])
@platform_required
def payment_verifications():
    from app.models.payment_verification import PaymentVerification
    status_filter = request.args.get("status", "pending")
    
    verifications = (
        PaymentVerification.query.filter_by(status=status_filter)
        .order_by(PaymentVerification.submitted_time.desc())
        .all()
    )
    
    # Calculate stats
    pending_count = PaymentVerification.query.filter_by(status="pending").count()
    approved_count = PaymentVerification.query.filter_by(status="approved").count()
    rejected_count = PaymentVerification.query.filter_by(status="rejected").count()
    
    return render_template(
        "platform/payment_verifications.html",
        verifications=verifications,
        current_filter=status_filter,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count
    )


@super_admin_bp.route("/payment-verifications/<int:vid>/verify", methods=["POST"])
@platform_required
def verify_payment_request(vid):
    from app.models.payment_verification import PaymentVerification
    from app.models.organization import Payment, Subscription
    from app.models.platform import Plan
    from datetime import datetime, timedelta
    
    verification = db.get_or_404(PaymentVerification, vid)
    action = request.form.get("action")
    remarks = request.form.get("remarks", "").strip()
    
    if verification.status != "pending":
        flash("This payment request has already been processed.", "warning")
        return redirect(url_for("super_admin.payment_verifications"))
        
    # Find the corresponding Payment record
    payment = Payment.query.filter_by(transaction_id=verification.transaction_id).first()
    
    if action == "approve":
        verification.status = "approved"
        verification.verification_time = datetime.utcnow()
        verification.verified_by = current_user.email
        verification.remarks = remarks or "Approved by Administrator."
        
        audit_log = list(verification.audit_log or [])
        audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "approved",
            "user_email": current_user.email,
            "details": f"Payment approved. Remarks: {remarks or 'None'}"
        })
        verification.audit_log = audit_log
        
        if payment:
            payment.status = "completed"
            
        # Process order/subscription details
        if verification.order_id.startswith("SUB-"):
            plan_id = int(verification.order_id.split("-")[1])
            plan = Plan.query.get(plan_id)
            if plan:
                sub = Subscription.query.filter_by(organization_id=verification.organization_id).first()
                if not sub:
                    sub = Subscription(organization_id=verification.organization_id)
                    db.session.add(sub)
                sub.plan = plan.name
                sub.status = "active"
                sub.billing_interval = plan.billing_interval
                sub.starts_at = datetime.utcnow()
                if plan.billing_interval == "yearly":
                    sub.expires_at = sub.starts_at + timedelta(days=365)
                else:
                    sub.expires_at = sub.starts_at + timedelta(days=30)
        elif verification.order_id.startswith("CE-"):
            from app.models import Campaign
            from app.models.campaign_express import CampaignExpressPayment
            from app.services.ce_number_allocator import CeNumberAllocator
            from app.services.campaign_runner import CampaignExecutionService

            campaign_id = int(verification.order_id.split("-")[1])
            campaign = Campaign.query.get(campaign_id)
            ce_payment = CampaignExpressPayment.query.filter_by(
                campaign_id=campaign_id, status="pending"
            ).order_by(CampaignExpressPayment.created_at.desc()).first()

            if ce_payment:
                ce_payment.status = "completed"
                ce_payment.transaction_id = verification.transaction_id
                ce_payment.completed_at = datetime.utcnow()

            if campaign:
                campaign.status = "ready"
                db.session.commit()

                # Allocate a pool number and trigger campaign execution
                assigned_number = CeNumberAllocator.allocate(campaign.id)
                if not assigned_number:
                    campaign.status = "queued"
                    db.session.commit()
                else:
                    campaign.status = "running"
                    db.session.commit()
                    try:
                        CampaignExecutionService.start(campaign.id)
                    except Exception as run_err:
                        CeNumberAllocator.release(campaign.id)
                        campaign.status = "ready"
                        db.session.commit()
                    
        db.session.commit()
        flash("Payment request successfully approved and processed!", "success")
        
    elif action == "reject":
        if not remarks:
            flash("Rejection remarks are required to reject a payment.", "danger")
            return redirect(url_for("super_admin.payment_verifications"))
            
        verification.status = "rejected"
        verification.verification_time = datetime.utcnow()
        verification.verified_by = current_user.email
        verification.remarks = remarks
        
        audit_log = list(verification.audit_log or [])
        audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "rejected",
            "user_email": current_user.email,
            "details": f"Payment rejected. Remarks: {remarks}"
        })
        verification.audit_log = audit_log
        
        if payment:
            payment.status = "failed"
            
        # Process campaign express rejection if applicable
        if verification.order_id.startswith("CE-"):
            from app.models.campaign_express import CampaignExpressPayment
            campaign_id = int(verification.order_id.split("-")[1])
            ce_payment = CampaignExpressPayment.query.filter_by(
                campaign_id=campaign_id, status="pending"
            ).order_by(CampaignExpressPayment.created_at.desc()).first()
            if ce_payment:
                ce_payment.status = "failed"

        # Notify Organization
        if verification.organization_id:
            from app.models.chat import DashboardNotification
            db_notif = DashboardNotification(
                organization_id=verification.organization_id,
                type="billing",
                title="UPI Payment Verification Failed",
                message=f"Manual payment verification failed. Reason: {remarks}",
                link="/org/profile"
            )
            db.session.add(db_notif)
        
        db.session.commit()
        flash("Payment request rejected.", "info")
        
    return redirect(url_for("super_admin.payment_verifications"))


@super_admin_bp.route("/changes")
@platform_required
def pending_changes():
    requests = (
        ChangeRequest.query.filter_by(status="pending")
        .order_by(ChangeRequest.created_at.desc())
        .all()
    )
    pending_orgs = (
        Organization.query.filter_by(status="pending")
        .order_by(Organization.created_at.desc())
        .all()
    )
    return render_template(
        "platform/pending_changes.html", requests=requests, pending_orgs=pending_orgs
    )


@super_admin_bp.route("/changes/<int:rid>/review", methods=["POST"])
@platform_required
def review_change(rid):
    req = db.get_or_404(ChangeRequest, rid)
    action = request.form.get("action")

    if action == "approve":
        if req.field_name == "org_name":
            org = db.session.get(Organization, req.organization_id)
            if org:
                org.name = req.new_value
        elif req.field_name == "admin_email":
            user = db.session.get(OrganizationUser, req.user_id)
            if user:
                user.email = req.new_value
        elif req.field_name == "password_reset":
            user = db.session.get(OrganizationUser, req.user_id)
            if user:
                user.password_hash = req.new_value

        req.status = "approved"
        flash("Change request approved and applied", "success")
    else:
        req.status = "rejected"
        flash("Change request rejected", "warning")

    req.reviewed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("super_admin.pending_changes"))


@super_admin_bp.route("/settings/admins", methods=["GET", "POST"])
@platform_required
def manage_admins():
    sec = PlatformSecurity.get_settings()

    if request.method == "POST":
        sec.default_admin_enabled = "default_admin_enabled" in request.form
        db.session.commit()
        flash("Platform security settings updated", "success")
        return redirect(url_for("super_admin.manage_admins"))

    admins = PlatformAdmin.query.all()
    return render_template(
        "platform/settings_admins.html",
        admins=admins,
        security=sec,
        default_email=Config.DEFAULT_ADMIN_EMAIL,
    )


@super_admin_bp.route("/settings/preferences", methods=["POST"])
@platform_required
def update_preferences():
    theme = request.form.get("theme", "light")
    language = request.form.get("language", "English")
    
    prefs = current_user.preferences or {}
    prefs["theme"] = theme
    prefs["language"] = language
    
    current_user.preferences = prefs
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, "preferences")
    db.session.commit()
    
    flash("Preferences updated successfully", "success")
    return redirect(url_for("super_admin.manage_admins"))


@super_admin_bp.route("/settings/branding", methods=["GET", "POST"])
@platform_required
def branding_settings():
    from app.models.platform import PlatformBranding
    from flask import current_app
    import os
    import time
    
    branding = PlatformBranding.get_settings()
    
    if request.method == "POST":
        brand_name = request.form.get("brand_name", "").strip()
        logo_display = request.form.get("logo_display", "both")
        logo_position = request.form.get("logo_position", "left")
        
        try:
            text_size = int(request.form.get("text_size", 24))
            logo_height = int(request.form.get("logo_height", 38))
        except ValueError:
            text_size = 24
            logo_height = 38
            
        if brand_name:
            branding.brand_name = brand_name
        branding.logo_display = logo_display
        branding.logo_position = logo_position
        branding.text_size = text_size
        branding.logo_height = logo_height
        
        # Save dynamic contact fields
        support_email = request.form.get("support_email", "").strip()
        sales_email = request.form.get("sales_email", "").strip()
        billing_email = request.form.get("billing_email", "").strip()
        legal_email = request.form.get("legal_email", "").strip()
        privacy_email = request.form.get("privacy_email", "").strip()
        dpo_email = request.form.get("dpo_email", "").strip()
        contact_phone = request.form.get("contact_phone", "").strip()

        if support_email:
            branding.support_email = support_email
        if sales_email:
            branding.sales_email = sales_email
        if billing_email:
            branding.billing_email = billing_email
        if legal_email:
            branding.legal_email = legal_email
        if privacy_email:
            branding.privacy_email = privacy_email
        if dpo_email:
            branding.dpo_email = dpo_email
        if contact_phone:
            branding.contact_phone = contact_phone

        
        # Handle file upload
        if "logo_file" in request.files:
            file = request.files["logo_file"]
            if file and file.filename != "":
                allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
                ext = os.path.splitext(file.filename)[1].lower()
                if ext in allowed_extensions:
                    filename = f"platform_logo_{int(time.time())}{ext}"
                    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "branding")
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    file.save(file_path)
                    branding.logo_path = f"uploads/branding/{filename}"
                else:
                    flash("Invalid file extension. Please upload an image file.", "danger")
                    
        db.session.commit()
        flash("Branding configurations saved successfully!", "success")
        return redirect(url_for("super_admin.branding_settings"))
        
    return render_template("platform/settings_branding.html", branding=branding)


@super_admin_bp.route("/settings/admins/add", methods=["POST"])
@platform_required
def add_admin():
    email = request.form.get("email")
    password = request.form.get("password")

    if not email or not password:
        flash("Email and password are required", "danger")
        return redirect(url_for("super_admin.manage_admins"))

    exists = PlatformAdmin.query.filter_by(email=email).first()
    if exists:
        flash("An admin with this email already exists", "danger")
        return redirect(url_for("super_admin.manage_admins"))

    new_admin = PlatformAdmin(
        email=email, password_hash=generate_password_hash(password)
    )
    db.session.add(new_admin)
    db.session.commit()
    flash(f"Platform admin {email} added successfully", "success")
    return redirect(url_for("super_admin.manage_admins"))


@super_admin_bp.route("/settings/admins/update/<int:aid>", methods=["POST"])
@platform_required
def update_admin(aid):
    admin = db.get_or_404(PlatformAdmin, aid)
    email = request.form.get("email")
    password = request.form.get("password")

    if email:
        admin.email = email
    if password:
        admin.password_hash = generate_password_hash(password)

    db.session.commit()
    flash(f"Admin {admin.email} updated", "success")
    return redirect(url_for("super_admin.manage_admins"))


@super_admin_bp.route("/settings/admins/delete/<int:aid>", methods=["POST"])
@platform_required
def delete_admin(aid):
    admin = db.get_or_404(PlatformAdmin, aid)

    if admin.id == current_user.id:
        flash("You cannot delete your own account while logged in.", "danger")
        return redirect(url_for("super_admin.manage_admins"))

    db.session.delete(admin)
    db.session.commit()
    flash(f"Admin {admin.email} removed", "info")
    return redirect(url_for("super_admin.manage_admins"))


@super_admin_bp.route("/helpdesk")
@platform_required
def helpdesk():
    from app.models.helpdesk import HelpdeskQuery
    from app.models.inquiry import Inquiry

    # Support tickets
    queries = HelpdeskQuery.query.order_by(HelpdeskQuery.created_at.desc()).all()
    total_queries = len(queries)
    pending_queries = sum(1 for q in queries if q.status == "Pending")
    resolved_queries = total_queries - pending_queries

    # Inquiries / Talk-to-Us leads
    inquiries = Inquiry.query.order_by(Inquiry.created_at.desc()).all()
    new_inquiry_count = sum(1 for i in inquiries if i.status == "New")

    return render_template(
        "platform/helpdesk.html",
        queries=queries,
        total_queries=total_queries,
        pending_queries=pending_queries,
        resolved_queries=resolved_queries,
        inquiries=inquiries,
        new_inquiry_count=new_inquiry_count,
    )


@super_admin_bp.route("/helpdesk/<int:qid>/resolve", methods=["POST"])
@platform_required
def resolve_query(qid):
    from app.models.helpdesk import HelpdeskQuery
    from app.models import DashboardNotification
    
    query = db.get_or_404(HelpdeskQuery, qid)
    query.status = "Resolved"
    query.resolved_at = datetime.utcnow()
    
    # Notify user who raised it
    db_notif = DashboardNotification(
        user_id=query.user_id,
        organization_id=query.organization_id,
        type="system",
        title=f"Support Query {query.ticket_number} Resolved",
        message="Your raised support ticket has been solved by the platform administrator.",
        link="/org/dashboard" if query.user_type == "org_admin" else "/worker/dashboard"
    )
    db.session.add(db_notif)
    
    db.session.commit()
    flash(f"Ticket {query.ticket_number} has been resolved successfully.", "success")
    return redirect(url_for("super_admin.helpdesk"))


@super_admin_bp.route("/logout")
@login_required
def logout():
    from app.security.session_manager import SessionManager

    SessionManager.logout_and_clean()
    return redirect(url_for("main.index"))


# ── Inquiry / Talk-to-Us Leads ─────────────────────────────────────────────────
@super_admin_bp.route("/inquiries")
@platform_required
def inquiries():
    from app.models.inquiry import Inquiry
    all_inquiries = Inquiry.query.order_by(Inquiry.created_at.desc()).all()
    total = len(all_inquiries)
    new_count = sum(1 for i in all_inquiries if i.status == "New")
    contacted = sum(1 for i in all_inquiries if i.status == "Contacted")
    qualified = sum(1 for i in all_inquiries if i.status == "Qualified")
    return render_template(
        "platform/inquiries.html",
        inquiries=all_inquiries,
        total=total,
        new_count=new_count,
        contacted=contacted,
        qualified=qualified,
    )


@super_admin_bp.route("/inquiries/<int:iid>/remark", methods=["POST"])
@platform_required
def inquiry_remark(iid):
    from app.models.inquiry import Inquiry
    inquiry = db.get_or_404(Inquiry, iid)
    remark = request.form.get("remark", "").strip()
    status = request.form.get("status", inquiry.status).strip()
    inquiry.admin_remark = remark
    inquiry.status = status
    db.session.commit()
    flash("Inquiry updated successfully.", "success")
    return redirect(url_for("super_admin.helpdesk") + "#inquiries")

# ── Campaign Express Platform Admin ─────────────────────────────────────────────

@super_admin_bp.route("/ce/users")
@platform_required
def ce_users():
    from app.models.campaign_express import CampaignExpressUser
    users = CampaignExpressUser.query.order_by(CampaignExpressUser.created_at.desc()).all()
    return render_template("platform/ce/ce_users.html", users=users)

@super_admin_bp.route("/ce/users/<int:uid>")
@platform_required
def ce_user_detail(uid):
    from app.models.campaign_express import CampaignExpressUser
    user = db.get_or_404(CampaignExpressUser, uid)
    return render_template("platform/ce/ce_user_detail.html", user=user)

@super_admin_bp.route("/ce/verification")
@platform_required
def ce_verification():
    from app.models.campaign_express import CampaignExpressUser, CampaignExpressPayment
    users = CampaignExpressUser.query.order_by(CampaignExpressUser.created_at.desc()).all()
    return render_template("platform/ce/ce_verification.html", users=users)

@super_admin_bp.route("/ce/number-pool")
@platform_required
def ce_number_pool():
    from app.models.ce_number_pool import CeNumberPool
    numbers = CeNumberPool.query.order_by(CeNumberPool.created_at.desc()).all()
    return render_template("platform/ce/ce_number_pool.html", numbers=numbers)

@super_admin_bp.route("/ce/number-pool/add", methods=["POST"])
@platform_required
def ce_number_pool_add():
    from app.models.ce_number_pool import CeNumberPool
    number = request.form.get("number")
    label = request.form.get("label")
    provider = request.form.get("provider", "twilio")
    api_token = request.form.get("api_token")
    auth_token = request.form.get("auth_token")
    if number and label:
        pool_num = CeNumberPool(
            number=number,
            label=label,
            provider=provider,
            api_token=api_token,
            auth_token=auth_token,
            is_active=True,
            is_healthy=True
        )
        db.session.add(pool_num)
        db.session.commit()
        flash("Number added successfully.", "success")
    return redirect(url_for("super_admin.ce_number_pool"))

@super_admin_bp.route("/ce/number-pool/<int:nid>/toggle", methods=["POST"])
@platform_required
def ce_number_pool_toggle(nid):
    from app.models.ce_number_pool import CeNumberPool
    num = db.get_or_404(CeNumberPool, nid)
    num.is_active = not num.is_active
    db.session.commit()
    flash(f"Number {'enabled' if num.is_active else 'disabled'} successfully.", "success")
    return redirect(url_for("super_admin.ce_number_pool"))

@super_admin_bp.route("/ce/campaigns")
@platform_required
def ce_campaigns():
    from app.models import Campaign
    campaigns = Campaign.query.filter(Campaign.campaign_express_user_id.isnot(None)).order_by(Campaign.created_at.desc()).all()
    return render_template("platform/ce/ce_campaigns.html", campaigns=campaigns)

@super_admin_bp.route("/ce/payments")
@platform_required
def ce_payments():
    from app.models.campaign_express import CampaignExpressPayment
    payments = CampaignExpressPayment.query.order_by(CampaignExpressPayment.created_at.desc()).all()
    return render_template("platform/ce/ce_payments.html", payments=payments)

