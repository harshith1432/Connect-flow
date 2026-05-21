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

                login_user(admin, remember="remember" in request.form)
                SessionManager.regenerate_session()
                SessionManager.track_session(admin.id, user_type)
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

    # Calculate revenue (completed payments)
    total_revenue = (
        db.session.query(func.sum(Payment.amount))
        .filter(Payment.status == "completed")
        .scalar()
    )
    if total_revenue is None:
        total_revenue = 0.0

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
    )


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

        method_id = request.form.get("method_id")
        if method_id:
            pm = db.session.get(PaymentMethod, method_id)
            if pm:
                pm.name = name
                pm.type = method_type
                pm.instructions = instructions
                flash(f"Payment method {name} updated", "success")
        else:
            pm = PaymentMethod(name=name, type=method_type, instructions=instructions)
            db.session.add(pm)
            flash(f"Payment method {name} added", "success")

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
    # Query all helpdesk tickets in chronological order
    queries = HelpdeskQuery.query.order_by(HelpdeskQuery.created_at.desc()).all()
    
    # Simple KPI counts
    total_queries = len(queries)
    pending_queries = sum(1 for q in queries if q.status == "Pending")
    resolved_queries = total_queries - pending_queries
    
    return render_template(
        "platform/helpdesk.html",
        queries=queries,
        total_queries=total_queries,
        pending_queries=pending_queries,
        resolved_queries=resolved_queries
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
