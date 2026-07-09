from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.extensions import db
from app.models import (
    Organization,
    OrganizationUser,
    Subscription,
    PlatformNotification,
)
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import os
import re
from sqlalchemy import text

main_bp = Blueprint(
    "main",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/main_static",
)


@main_bp.route("/subscription-expired")
def subscription_expired():
    return render_template("main/subscription_expired.html")


@main_bp.route("/")
def index():
    # Health check: verify DB connection
    db_ok = True
    db_error = None
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as e:
        db_ok = False
        db_error = str(e)
    return render_template("index.html", db_ok=db_ok, db_error=db_error)


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    from flask_login import current_user, login_user
    from app.models import PlatformAdmin, CampaignExpressUser, OrganizationUser, Subscription
    from app.security.auth_protection import BruteForceProtection
    from app.security.mfa import MFAService
    from app.security.session_manager import SessionManager
    from datetime import datetime, timedelta
    from urllib.parse import urlparse

    if current_user.is_authenticated:
        if hasattr(current_user, "role") and current_user.role == "platform_owner":
            return redirect(url_for("super_admin.dashboard"))
        elif hasattr(current_user, "role") and current_user.role == "campaign_express":
            return redirect(url_for("campaign_express.dashboard"))
        elif hasattr(current_user, "role") and current_user.role == "org_admin":
            return redirect(url_for("org.dashboard"))
        else:
            return redirect(url_for("worker.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        account_type = request.form.get("account_type")
        account_id = request.form.get("account_id")

        import requests
        from flask import current_app

        hcaptcha_secret = current_app.config.get("HCAPTCHA_SECRET")
        if hcaptcha_secret:
            hcaptcha_response = request.form.get("h-captcha-response")
            if not hcaptcha_response:
                flash("Please complete the Captcha verification.", "danger")
                return render_template("auth/login.html")

            try:
                r = requests.post("https://api.hcaptcha.com/siteverify", data={
                    "secret": hcaptcha_secret,
                    "response": hcaptcha_response
                }, timeout=5)
                result = r.json()
                if not result.get("success"):
                    flash("Captcha verification failed. Please try again.", "danger")
                    return render_template("auth/login.html")
            except requests.exceptions.RequestException:
                flash("Failed to contact Captcha service. Please try again later.", "danger")
                return render_template("auth/login.html")

        locked, lock_msg = BruteForceProtection.is_locked_out(email)
        if locked:
            flash(lock_msg, "danger")
            return render_template("auth/login.html")

        valid_accounts = []

        # 1. Platform Admin check
        p_admin = PlatformAdmin.query.filter_by(email=email).first()
        if p_admin and p_admin.check_password(password):
            valid_accounts.append(('platform_admin', p_admin))

        # 2. Campaign Express check
        ce_user = CampaignExpressUser.query.filter_by(email=email).first() or CampaignExpressUser.query.filter_by(username=email).first()
        if ce_user and ce_user.check_password(password):
            valid_accounts.append(('campaign_express_user', ce_user))

        # 3. Organization user check
        org_users = OrganizationUser.query.filter_by(email=email).all()
        for u in org_users:
            if u.check_password(password):
                valid_accounts.append(('organization_user', u))

        if not valid_accounts:
            BruteForceProtection.log_failed_attempt(identifier=email)
            flash("Invalid credentials", "danger")
            return render_template("auth/login.html")

        selected_account = None
        if account_type and account_id:
            for t, acc in valid_accounts:
                if t == account_type and str(acc.id) == str(account_id):
                    selected_account = (t, acc)
                    break

        if not selected_account:
            if len(valid_accounts) == 1:
                selected_account = valid_accounts[0]
            else:
                return render_template(
                    "auth/select_portal.html",
                    matching_accounts=valid_accounts,
                    email=email,
                    password=password,
                )

        user_type, user = selected_account

        # Finalize login
        if user_type == "platform_admin":
            mfa_type = "platform_admin"
            config = MFAService.get_mfa_config(user.id, mfa_type)
            if config.is_enabled:
                from flask import session
                session["pre_mfa_user_id"] = user.id
                session["pre_mfa_user_type"] = mfa_type
                session["pre_mfa_remember"] = "remember" in request.form
                success, msg = MFAService.generate_and_send_otp(user.id, mfa_type, method=config.mfa_type)
                if success:
                    flash("Verification code sent.", "info")
                    return redirect(url_for("security.verify_otp"))
                else:
                    flash(f"Error sending verification code: {msg}", "danger")
                    return render_template("auth/login.html")
            else:
                login_user(user, remember="remember" in request.form)
                SessionManager.regenerate_session()
                SessionManager.track_session(user.id, mfa_type)
                
                next_page = request.args.get("next")
                if next_page:
                    parsed = urlparse(next_page)
                    if parsed.netloc == "" or parsed.netloc == request.host:
                        return redirect(next_page)
                return redirect(url_for("super_admin.dashboard"))

        elif user_type == "campaign_express_user":
            user.login_count = (user.login_count or 0) + 1
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            login_user(user, remember="remember" in request.form)
            SessionManager.regenerate_session()
            SessionManager.track_session(user.id, "campaign_express")
            
            next_page = request.args.get("next")
            if next_page:
                parsed = urlparse(next_page)
                if parsed.netloc == "" or parsed.netloc == request.host:
                    return redirect(next_page)
            return redirect(url_for("campaign_express.dashboard"))

        elif user_type == "organization_user":
            org_status = user.organization.status
            if org_status == "pending":
                return render_template("auth/access_denied.html", status="pending", org_name=user.organization.name)
            elif org_status == "rejected":
                return render_template("auth/access_denied.html", status="rejected", org_name=user.organization.name, reason=user.organization.description)
            elif org_status == "suspended":
                flash("Your organization has been suspended. Please contact platform admin.", "danger")
                return render_template("auth/login.html")

            # Subscription check for workers
            if user.role != "org_admin":
                sub = Subscription.query.filter_by(organization_id=user.organization_id).first()
                if not sub or sub.status == "inactive" or (sub.expires_at and datetime.utcnow() > sub.expires_at + timedelta(days=3)):
                    flash("Organization services are suspended or a subscription is required.", "danger")
                    return render_template("auth/login.html")

            user.login_count = (user.login_count or 0) + 1
            user.last_login = datetime.utcnow()
            db.session.commit()

            from app.models import ChangeRequest
            ChangeRequest.log(user.organization_id, user.id, "User Login", new_val=f"Session started from {request.remote_addr}")

            mfa_type = "org_user"
            config = MFAService.get_mfa_config(user.id, mfa_type)
            if config.is_enabled:
                from flask import session
                session["pre_mfa_user_id"] = user.id
                session["pre_mfa_user_type"] = mfa_type
                session["pre_mfa_remember"] = "remember" in request.form
                success, msg = MFAService.generate_and_send_otp(user.id, mfa_type, method=config.mfa_type)
                if success:
                    flash("Verification code sent.", "info")
                    return redirect(url_for("security.verify_otp"))
                else:
                    flash(f"Error sending verification code: {msg}", "danger")
                    return render_template("auth/login.html")
            else:
                login_user(user, remember="remember" in request.form)
                SessionManager.regenerate_session()
                SessionManager.track_session(user.id, mfa_type)
                
                next_page = request.args.get("next")
                if next_page:
                    parsed = urlparse(next_page)
                    if parsed.netloc == "" or parsed.netloc == request.host:
                        return redirect(next_page)
                
                if user.role == "org_admin":
                    return redirect(url_for("org.dashboard"))
                else:
                    return redirect(url_for("worker.dashboard"))

    return render_template("auth/login.html")


@main_bp.route("/org/register", methods=["GET", "POST"])
def org_register():
    if request.method == "POST":
        # Step 1: Org Details
        org_name = request.form.get("org_name")
        org_type = request.form.get("org_type")
        industry = request.form.get("industry")
        country = request.form.get("country")
        office_address = request.form.get("office_address")

        # Step 2: Admin Details
        email = request.form.get("email")
        password = request.form.get("password")
        full_name = request.form.get("full_name")
        designation = request.form.get("designation")
        phone = request.form.get("phone")

        # Step 3: Branding & Support
        language_preference = request.form.get("language_preference", "English")
        support_email = request.form.get("support_email")
        support_phone = request.form.get("support_phone")

        # Basic validation
        if not all([org_name, email, password]):
            flash("Company name, Email, and Password are required.", "danger")
            return render_template("auth/register_stepper.html"), 400

        # Validate Phone Number (10 digits)
        if phone and not re.match(r"^\d{10}$", phone):
            flash("Mobile Number must be exactly 10 digits.", "danger")
            return render_template("auth/register_stepper.html"), 400

        # Validate Email Format
        if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Please enter a valid email address.", "danger")
            return render_template("auth/register_stepper.html"), 400

        # Validate Support Contacts
        if support_phone and not re.match(r"^\d{10}$", support_phone):
            flash("Public Support Phone must be exactly 10 digits.", "danger")
            return render_template("auth/register_stepper.html"), 400

        if support_email and not re.match(r"[^@]+@[^@]+\.[^@]+", support_email):
            flash("Please enter a valid support email address.", "danger")
            return render_template("auth/register_stepper.html"), 400

        # Check if email exists
        existing_user = (
            db.session.query(OrganizationUser).filter_by(email=email).first()
        )
        if existing_user:
            flash("Email already registered.", "danger")
            return render_template("auth/register_stepper.html"), 400

        # Handle Logo Upload
        logo_url = None
        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename:
            filename = secure_filename(f"{org_name}_{logo_file.filename}")
            upload_path = os.path.join("app", "static", "uploads", "logos", filename)
            # Ensure directory exists (mkdir -p logic)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            logo_file.save(upload_path)
            logo_url = f"uploads/logos/{filename}"

        # 1. Create Organization (Pending)
        org = Organization(
            name=org_name,
            org_type=org_type,
            industry=industry,
            country=country,
            office_address=office_address,
            logo_url=logo_url,
            language_preference=language_preference,
            support_email=support_email,
            support_phone=support_phone,
            status="pending",  # Explicitly set to pending
        )
        db.session.add(org)
        db.session.flush()

        # 2. Create Subscription (Trial)
        sub = Subscription(organization_id=org.id, plan="Trial", status="active")
        db.session.add(sub)

        # 3. Create Admin User
        user = OrganizationUser(
            organization_id=org.id,
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            role="org_admin",
            designation=designation,
            phone=phone,
        )
        db.session.add(user)

        # 4. Create Platform Notification for Admin
        notification = PlatformNotification(
            organization_id=org.id,
            type="new_organization",
            message=f'New organization "{org_name}" has registered and is awaiting approval',
            is_read=False,
        )
        db.session.add(notification)

        db.session.commit()

        return redirect(url_for("main.registration_success"))

    return render_template("auth/register_stepper.html")


@main_bp.route("/org/registration-success")
def registration_success():
    return render_template("auth/registration_success.html")


@main_bp.route("/verification-pending")
def verification_pending():
    return render_template("auth/verification_pending.html")


# OAuth routes
@main_bp.route("/google-auth")
def google_auth():
    import urllib.parse
    from flask import current_app, redirect, url_for

    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    redirect_uri = url_for("main.google_callback", _external=True)
    scope = "openid email profile"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    }
    google_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return redirect(google_url)

# OAuth callback
@main_bp.route("/callback")
def google_callback():
    import requests
    from flask import current_app, session
    from flask_login import login_user
    from datetime import datetime, timedelta

    code = request.args.get("code")
    if not code:
        flash("Google login failed", "danger")
        return redirect(url_for("worker.login"))

    google_client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    google_client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = url_for("main.google_callback", _external=True)

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": google_client_id,
        "client_secret": google_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    r = requests.post(token_url, data=data)
    if not r.ok:
        flash("Failed to retrieve token from Google", "danger")
        return redirect(url_for("worker.login"))

    access_token = r.json().get("access_token")
    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    r = requests.get(userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
    if not r.ok:
        flash("Failed to get user info from Google", "danger")
        return redirect(url_for("worker.login"))

    email = r.json().get("email")
    if not email:
        flash("Google did not return an email", "danger")
        return redirect(url_for("worker.login"))

    matching_users = OrganizationUser.query.filter_by(email=email).all()
    if not matching_users:
        flash("No account associated with this email", "danger")
        return redirect(url_for("worker.login"))

    if len(matching_users) == 1:
        user = matching_users[0]
        sub = Subscription.query.filter_by(organization_id=user.organization_id).first()
        if (
            not sub
            or sub.status == "inactive"
            or (
                sub.expires_at
                and datetime.utcnow() > sub.expires_at + timedelta(days=3)
            )
        ):
            flash(
                "Organization services are suspended or a subscription is required. Please contact your administrator.",
                "danger",
            )
            return redirect(url_for("worker.login"))
        login_user(user)
        # Session hardening for OAuth login
        from app.security.session_manager import SessionManager

        SessionManager.regenerate_session()
        SessionManager.track_session(user.id, "org_user")
        return redirect(url_for("worker.dashboard"))

    session["oauth_email"] = email
    return redirect(url_for("worker.oauth_select_org"))


# Legal Document Routes
@main_bp.route("/legal/terms-of-service")
def terms_of_service():
    return render_template("legal/terms_of_service.html")


@main_bp.route("/legal/privacy-policy")
def privacy_policy():
    return render_template("legal/privacy_policy.html")


@main_bp.route("/legal/dpa")
def dpa():
    return render_template("legal/dpa.html")


# ── Product Pages ──────────────────────────────────────────────────────────────
@main_bp.route("/features")
def features():
    return render_template("main/features.html")


@main_bp.route("/solutions")
def solutions():
    return render_template("main/solutions.html")


@main_bp.route("/pricing")
def pricing():
    return render_template("main/pricing.html")


@main_bp.route("/changelog")
def changelog():
    return render_template("main/changelog.html")


# ── Company Pages ──────────────────────────────────────────────────────────────
@main_bp.route("/about")
def about():
    return render_template("main/about.html")


@main_bp.route("/careers")
def careers():
    return render_template("main/careers.html")


@main_bp.route("/blog")
def blog():
    return render_template("main/blog.html")


@main_bp.route("/contact", methods=["GET", "POST"])
def contact():
    submitted = False
    if request.method == "POST":
        submitted = True
    return render_template("main/contact.html", submitted=submitted)


# ── Resources Pages ────────────────────────────────────────────────────────────
@main_bp.route("/docs")
def documentation():
    return render_template("main/documentation.html")


@main_bp.route("/api-reference")
def api_reference():
    return render_template("main/api_reference.html")


@main_bp.route("/status")
def system_status():
    return render_template("main/system_status.html")


@main_bp.route("/help")
def help_center():
    return render_template("main/help_center.html")


# ── Talk-to-Us Inquiry Submission ──────────────────────────────────────────────
@main_bp.route("/inquiry", methods=["POST"])
def submit_inquiry():
    from app.models.inquiry import Inquiry
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    company_name = request.form.get("company_name", "").strip()
    reason = request.form.get("reason", "General Enquiry").strip()
    message = request.form.get("message", "").strip()
    source_page = request.form.get("source_page", "unknown").strip()

    if not name or not email:
        flash("Name and email are required.", "danger")
        return redirect(request.referrer or url_for("main.index"))

    inquiry = Inquiry(
        name=name,
        email=email,
        phone=phone,
        company_name=company_name,
        reason=reason,
        message=message,
        source_page=source_page,
        status="New",
    )
    db.session.add(inquiry)
    db.session.commit()
    flash("Thank you! We'll be in touch shortly.", "success")
    return redirect(request.referrer or url_for("main.index"))


