"""
Campaign Express Blueprint — routes.py
All routes for standalone campaign users who don't belong to any organization.
Reuses existing campaign engine, analytics, and report systems.
"""
import os
import re
import uuid
import json
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
    current_app,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app.extensions import db, csrf
from app.models import (
    Campaign,
    CampaignTarget,
    DeliveryLog,
    Script,
)
from app.models.campaign_express import CampaignExpressUser, CampaignExpressPayment
from app.core.decorators import campaign_express_required

campaign_express_bp = Blueprint(
    "campaign_express",
    __name__,
    url_prefix="/campaign-express",
    template_folder="templates",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_DOC_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
CAMPAIGN_PURPOSE_OPTIONS = [
    "Marketing",
    "Event Invitations",
    "Customer Notifications",
    "Education",
    "Surveys",
    "General Communication",
]
IDENTITY_TYPE_OPTIONS = [
    "Aadhaar Card",
    "Passport",
    "Driving License",
    "PAN Card",
    "Voter ID",
    "Other Government ID",
]


def _allowed_doc(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_DOC_EXTENSIONS


def _generate_username(email: str) -> str:
    """Generate a unique username from email prefix."""
    base = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())
    base = base[:20] or "user"
    suffix = uuid.uuid4().hex[:6]
    candidate = f"{base}_{suffix}"
    # Ensure uniqueness
    while CampaignExpressUser.query.filter_by(username=candidate).first():
        candidate = f"{base}_{uuid.uuid4().hex[:6]}"
    return candidate


def _save_upload(file, subfolder: str) -> str:
    """Save an uploaded file and return the relative path."""
    filename = secure_filename(f"ce_{uuid.uuid4().hex}_{file.filename}")
    upload_dir = os.path.join("app", "static", "uploads", subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return f"uploads/{subfolder}/{filename}"


def _get_ce_campaigns(user_id):
    return Campaign.query.filter_by(campaign_express_user_id=user_id).order_by(Campaign.created_at.desc())


def _campaign_kpis(user_id):
    campaigns = _get_ce_campaigns(user_id).all()
    c_ids = [c.id for c in campaigns]

    total_campaigns   = len(campaigns)
    campaigns_executed = sum(1 for c in campaigns if c.status == "completed")

    total_logs   = DeliveryLog.query.filter(DeliveryLog.campaign_id.in_(c_ids)).count() if c_ids else 0
    success_logs = DeliveryLog.query.filter(
        DeliveryLog.campaign_id.in_(c_ids),
        DeliveryLog.status.in_(["sent", "delivered", "read", "completed"]),
    ).count() if c_ids else 0
    calls_completed = success_logs

    success_rate = round((success_logs / total_logs * 100), 1) if total_logs > 0 else 0.0

    total_spend = db.session.query(db.func.sum(CampaignExpressPayment.amount)).filter(
        CampaignExpressPayment.user_id == user_id,
        CampaignExpressPayment.status == "completed",
    ).scalar() or 0.0

    reports_generated = campaigns_executed  # 1 report auto-generates per completed campaign

    return {
        "total_campaigns":    total_campaigns,
        "campaigns_executed": campaigns_executed,
        "calls_completed":    calls_completed,
        "success_rate":       success_rate,
        "total_spend":        round(total_spend, 2),
        "reports_generated":  reports_generated,
    }


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Registration (Manual, 3-step)
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated and getattr(current_user, "role", "") == "campaign_express":
        return redirect(url_for("campaign_express.dashboard"))

    if request.method == "POST":
        # ── Step 1 — Account ─────────────────────────────────────────────────
        first_name       = request.form.get("first_name", "").strip()
        last_name        = request.form.get("last_name", "").strip()
        email            = request.form.get("email", "").strip().lower()
        password         = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # ── Step 2 — Personal Details ─────────────────────────────────────────
        address_line1    = request.form.get("address_line1", "").strip()
        address_line2    = request.form.get("address_line2", "").strip()
        city             = request.form.get("city", "").strip()
        state            = request.form.get("state", "").strip()
        country          = request.form.get("country", "").strip()
        postal_code      = request.form.get("postal_code", "").strip()
        campaign_purpose = request.form.get("campaign_purpose", "General Communication")

        # ── Step 3 — Identity ────────────────────────────────────────────────
        identity_type   = request.form.get("identity_type", "").strip()
        identity_number = request.form.get("identity_number", "").strip()
        identity_doc_file = request.files.get("identity_document")

        # ── Validation ────────────────────────────────────────────────────────
        if not all([first_name, last_name, email, password, confirm_password,
                    address_line1, city, state, country, postal_code,
                    identity_type, identity_number]):
            flash("All registration, address, and identity verification details are required.", "danger")
            return render_template("campaign_express/auth/register.html",
                                   purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        if not identity_doc_file or not identity_doc_file.filename:
            flash("Identity verification document is required.", "danger")
            return render_template("campaign_express/auth/register.html",
                                   purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("campaign_express/auth/register.html",
                                   purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("campaign_express/auth/register.html",
                                   purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Please enter a valid email address.", "danger")
            return render_template("campaign_express/auth/register.html",
                                   purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        if CampaignExpressUser.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "danger")
            return render_template("campaign_express/auth/register.html",
                                   purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        # ── Handle identity document upload ───────────────────────────────────
        identity_document_path = None
        if identity_doc_file and identity_doc_file.filename:
            if not _allowed_doc(identity_doc_file.filename):
                flash("Document must be PDF, JPG, JPEG or PNG.", "danger")
                return render_template("campaign_express/auth/register.html",
                                       purposes=CAMPAIGN_PURPOSE_OPTIONS,
                                       identity_types=IDENTITY_TYPE_OPTIONS)
            identity_document_path = _save_upload(identity_doc_file, "ce_docs")

        # Generate unique username automatically on the backend
        username = _generate_username(email)

        # ── Determine verification status ─────────────────────────────────────
        # Since all details are required, verification_status is "verified"
        has_identity = bool(identity_type and identity_number and identity_document_path)
        verification_status = "verified" if has_identity else "profile_created"

        # ── Create user ───────────────────────────────────────────────────────
        user = CampaignExpressUser(
            first_name          = first_name,
            last_name           = last_name,
            username            = username,
            email               = email,
            campaign_purpose    = campaign_purpose,
            address_line1       = address_line1,
            address_line2       = address_line2,
            city                = city,
            state               = state,
            country             = country,
            postal_code         = postal_code,
            identity_type       = identity_type,
            identity_number     = identity_number,
            identity_document   = identity_document_path,
            verification_status = verification_status,
            auth_provider       = "manual",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Registration successful! Please sign in with your credentials.", "success")
        return redirect(url_for("campaign_express.login"))

    return render_template(
        "campaign_express/auth/register.html",
        purposes=CAMPAIGN_PURPOSE_OPTIONS,
        identity_types=IDENTITY_TYPE_OPTIONS,
    )


@campaign_express_bp.route("/register/success")
def register_success():
    verified = request.args.get("verified", "0") == "1"
    return render_template("campaign_express/auth/register_success.html", verified=verified)


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Login
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("main.login", **request.args))


@campaign_express_bp.route("/logout")
@login_required
def logout():
    from app.security.session_manager import SessionManager
    SessionManager.logout_and_clean()
    return redirect(url_for("campaign_express.login"))


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Google OAuth (CE-specific flow)
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/google-auth")
def google_auth():
    import urllib.parse
    client_id    = current_app.config.get("GOOGLE_CLIENT_ID")
    redirect_uri = url_for("campaign_express.google_callback", _external=True)
    scope        = "openid email profile"
    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         scope,
        "access_type":   "offline",
        "prompt":        "select_account",
        "state":         "campaign_express",
    }
    google_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return redirect(google_url)


@campaign_express_bp.route("/callback")
def google_callback():
    """CE-specific Google OAuth callback — creates or logs in a CampaignExpressUser."""
    import requests as http_requests

    code = request.args.get("code")
    if not code:
        flash("Google sign-in failed. Please try again.", "danger")
        return redirect(url_for("campaign_express.login"))

    google_client_id     = current_app.config.get("GOOGLE_CLIENT_ID")
    google_client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")
    redirect_uri         = url_for("campaign_express.google_callback", _external=True)

    # Exchange code for token
    token_resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code":          code,
            "client_id":     google_client_id,
            "client_secret": google_client_secret,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        },
    )
    if not token_resp.ok:
        flash("Failed to retrieve token from Google.", "danger")
        return redirect(url_for("campaign_express.login"))

    access_token = token_resp.json().get("access_token")
    info_resp    = http_requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not info_resp.ok:
        flash("Failed to get user info from Google.", "danger")
        return redirect(url_for("campaign_express.login"))

    info      = info_resp.json()
    google_id = info.get("sub")
    email     = info.get("email", "").lower()
    name      = info.get("name", "")
    picture   = info.get("picture", "")

    if not email:
        flash("Google did not return an email address.", "danger")
        return redirect(url_for("campaign_express.login"))

    # Find or create CampaignExpressUser
    user = CampaignExpressUser.query.filter_by(google_id=google_id).first()
    if not user:
        user = CampaignExpressUser.query.filter_by(email=email).first()

    if not user:
        # ── New Google user — auto-create ─────────────────────────────────────
        first_name = name.split()[0] if name else ""
        last_name  = " ".join(name.split()[1:]) if len(name.split()) > 1 else ""
        user = CampaignExpressUser(
            first_name          = first_name,
            last_name           = last_name,
            username            = _generate_username(email),
            email               = email,
            google_id           = google_id,
            profile_photo       = picture,
            auth_provider       = "google",
            verification_status = "profile_created",
        )
        db.session.add(user)
    else:
        # Update google_id if account existed via manual registration
        if not user.google_id:
            user.google_id     = google_id
            user.auth_provider = "google"

    user.login_count = (user.login_count or 0) + 1
    user.last_login  = datetime.utcnow()
    db.session.commit()

    login_user(user)
    from app.security.session_manager import SessionManager
    SessionManager.regenerate_session()
    SessionManager.track_session(user.id, "campaign_express")

    return redirect(url_for("campaign_express.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Forgot Password
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email        = request.form.get("email", "").strip().lower()
        new_password = request.form.get("new_password", "")

        user = CampaignExpressUser.query.filter_by(email=email).first()
        if not user:
            flash("No Campaign Express account found with this email.", "danger")
            return render_template("campaign_express/auth/forgot_password.html")

        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("campaign_express/auth/forgot_password.html")

        user.set_password(new_password)
        db.session.commit()
        flash("Password updated successfully. You can now log in.", "success")
        return redirect(url_for("campaign_express.login"))

    return render_template("campaign_express/auth/forgot_password.html")


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION BOARDING FLOW
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/verification", methods=["GET", "POST"])
@campaign_express_required
def verification():
    """Dedicated verification boarding screen — required before campaign execution."""
    user = current_user

    if user.is_verified:
        # Already verified — redirect to pending campaign if any
        pending_id = session.pop("pending_campaign_id", None)
        if pending_id:
            return redirect(url_for("campaign_express.campaign_detail", cid=pending_id))
        return redirect(url_for("campaign_express.dashboard"))

    if request.method == "POST":
        # ── Step 1 — Profile / Address ────────────────────────────────────────
        user.address_line1 = request.form.get("address_line1", user.address_line1 or "").strip()
        user.address_line2 = request.form.get("address_line2", user.address_line2 or "").strip()
        user.city          = request.form.get("city",          user.city          or "").strip()
        user.state         = request.form.get("state",         user.state         or "").strip()
        user.country       = request.form.get("country",       user.country       or "").strip()
        user.postal_code   = request.form.get("postal_code",   user.postal_code   or "").strip()

        # ── Step 2 — Identity ─────────────────────────────────────────────────
        user.identity_type   = request.form.get("identity_type",   "").strip()
        user.identity_number = request.form.get("identity_number", "").strip()

        identity_doc_file = request.files.get("identity_document")
        if identity_doc_file and identity_doc_file.filename:
            if not _allowed_doc(identity_doc_file.filename):
                flash("Document must be PDF, JPG, JPEG or PNG.", "danger")
                return render_template("campaign_express/auth/verification.html",
                                       identity_types=IDENTITY_TYPE_OPTIONS)
            user.identity_document = _save_upload(identity_doc_file, "ce_docs")

        # Validate required fields
        required = [user.address_line1, user.city, user.country,
                    user.identity_type, user.identity_number, user.identity_document]
        if not all(required):
            flash("Please complete all required fields and upload your document.", "danger")
            return render_template("campaign_express/auth/verification.html",
                                   identity_types=IDENTITY_TYPE_OPTIONS)

        user.verification_status = "verification_pending"
        db.session.commit()

        return redirect(url_for("campaign_express.verification_submitted"))

    return render_template(
        "campaign_express/auth/verification.html",
        identity_types=IDENTITY_TYPE_OPTIONS,
        user=user,
    )


@campaign_express_bp.route("/verification-submitted")
@campaign_express_required
def verification_submitted():
    return render_template("campaign_express/auth/verification_submitted.html")


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/dashboard")
@campaign_express_required
def dashboard():
    kpis     = _campaign_kpis(current_user.id)
    recent   = _get_ce_campaigns(current_user.id).limit(5).all()
    payments = CampaignExpressPayment.query.filter_by(
        user_id=current_user.id
    ).order_by(CampaignExpressPayment.created_at.desc()).limit(5).all()

    return render_template(
        "campaign_express/dashboard.html",
        kpis=kpis,
        recent_campaigns=recent,
        recent_payments=payments,
        user=current_user,
    )


@campaign_express_bp.route("/api/dashboard-analytics")
@campaign_express_required
def dashboard_analytics():
    c_ids = [c.id for c in _get_ce_campaigns(current_user.id).all()]
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    trend = (
        db.session.query(
            db.func.date(DeliveryLog.created_at),
            db.func.count(DeliveryLog.id),
        )
        .filter(
            DeliveryLog.campaign_id.in_(c_ids),
            DeliveryLog.created_at >= seven_days_ago,
        )
        .group_by(db.func.date(DeliveryLog.created_at))
        .all()
    ) if c_ids else []

    dist_raw = (
        db.session.query(Campaign.name, db.func.count(DeliveryLog.id))
        .join(DeliveryLog, DeliveryLog.campaign_id == Campaign.id)
        .filter(Campaign.campaign_express_user_id == current_user.id)
        .group_by(Campaign.name)
        .all()
    )

    return jsonify({
        "trend": {
            "labels": [str(t[0]) for t in trend],
            "data":   [t[1] for t in trend],
        },
        "distribution": {
            "labels": [d[0] for d in dist_raw],
            "data":   [d[1] for d in dist_raw],
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# CAMPAIGNS — List, Create, Detail, Edit, Delete, Duplicate, Archive
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/campaigns")
@campaign_express_required
def campaigns():
    status_filter = request.args.get("status", "")
    q = _get_ce_campaigns(current_user.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    all_campaigns = q.all()
    return render_template(
        "campaign_express/campaigns.html",
        campaigns=all_campaigns,
        status_filter=status_filter,
    )


@campaign_express_bp.route("/campaigns/create", methods=["GET", "POST"])
@campaign_express_required
def campaign_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        c_type = request.form.get("type", "call")

        if not name:
            flash("Campaign name is required.", "danger")
            return render_template("campaign_express/campaign_create.html")

        campaign = Campaign(
            name=name,
            type=c_type,
            status="draft",
            campaign_express_user_id=current_user.id,
            # organization_id intentionally left null for CE users
        )
        db.session.add(campaign)
        db.session.commit()

        flash(f"Campaign '{name}' created as draft.", "success")
        return redirect(url_for("campaign_express.campaign_detail", cid=campaign.id))

    return render_template("campaign_express/campaign_create.html")


@campaign_express_bp.route("/campaigns/<int:cid>")
@campaign_express_required
def campaign_detail(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    from app.models.modules import Module, ModuleGroup, ModuleField, ModuleRecord

    # Auto-initialize Module and Group if not present
    modified = False
    if not campaign.module_id:
        module = Module(
            name=f"CE Campaign {campaign.id} Module",
            description=f"Contacts module for CE Campaign {campaign.name}",
        )
        db.session.add(module)
        db.session.flush()
        campaign.module_id = module.id
        modified = True

    if not campaign.group_id:
        group = ModuleGroup(
            module_id=campaign.module_id,
            name=f"CE Campaign {campaign.id} Group",
        )
        db.session.add(group)
        db.session.flush()
        campaign.group_id = group.id
        modified = True

    if modified:
        db.session.commit()

    # Query fields and records
    fields = ModuleField.query.filter_by(module_id=campaign.module_id).order_by(ModuleField.id).all()
    records = ModuleRecord.query.filter_by(module_id=campaign.module_id, group_id=campaign.group_id).order_by(ModuleRecord.id.desc()).all()

    # Enrich records with calculated/boolean values
    for r in records:
        r.computed_values = {}
        f_vals = r.field_values
        for f in fields:
            if f.field_type in ["calculated", "boolean"]:
                r.computed_values[f.id] = evaluate_logic(r, f)
            else:
                r.computed_values[f.id] = f_vals.get(f.id, "-")

    # Delivery stats
    c_logs      = DeliveryLog.query.filter_by(campaign_id=cid).all()
    total_calls = len(c_logs)
    connected   = sum(1 for l in c_logs if l.status in ("completed", "sent", "delivered", "read"))
    rate        = round(connected / total_calls * 100, 1) if total_calls > 0 else 0

    # Cost estimate (stub: ₹1.50 per call)
    COST_PER_CALL = 1.50
    target_count  = CampaignTarget.query.filter_by(campaign_id=cid).count()
    estimated_cost = round(target_count * COST_PER_CALL, 2)

    # Latest payment for this campaign
    payment = CampaignExpressPayment.query.filter_by(
        campaign_id=cid, user_id=current_user.id
    ).order_by(CampaignExpressPayment.created_at.desc()).first()

    return render_template(
        "campaign_express/campaign_detail.html",
        campaign=campaign,
        fields=fields,
        records=records,
        total_calls=total_calls,
        connected=connected,
        rate=rate,
        estimated_cost=estimated_cost,
        target_count=target_count,
        payment=payment,
        user=current_user,
    )


@campaign_express_bp.route("/campaigns/<int:cid>/upload-contacts", methods=["POST"])
@campaign_express_required
def campaign_upload_contacts(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    if campaign.status in ("running", "completed"):
        flash("Cannot modify contacts for a running or completed campaign.", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    file = request.files.get("contacts_file")
    if not file or not file.filename:
        flash("No file selected.", "danger")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    if not file.filename.endswith(".csv"):
        flash("Please upload a CSV file.", "danger")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    import csv
    import io
    from app.models.modules import Module, ModuleGroup, ModuleField, ModuleRecord, ModuleRecordValue
    from app.models import CampaignTarget

    try:
        stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
        reader = csv.reader(stream)
        headers = [h.strip() for h in next(reader, [])]

        if not headers:
            flash("The CSV file is empty.", "danger")
            return redirect(url_for("campaign_express.campaign_detail", cid=cid))

        # Check for a phone column
        phone_col_idx = -1
        from app.services.campaign_runner import _PHONE_KEYS
        for idx, h in enumerate(headers):
            if h.lower() in _PHONE_KEYS:
                phone_col_idx = idx
                break

        if phone_col_idx == -1:
            phone_col_idx = 0
            flash("No explicit phone/number column found. Using the first column for phone numbers.", "warning")

        # 1. Create or retrieve Module and ModuleGroup for this campaign
        module = None
        if campaign.module_id:
            module = db.session.get(Module, campaign.module_id)
        if not module:
            module = Module(
                name=f"CE Campaign {campaign.id} Module",
                description=f"Contacts module for CE Campaign {campaign.name}",
            )
            db.session.add(module)
            db.session.flush()
            campaign.module_id = module.id

        group = None
        if campaign.group_id:
            group = db.session.get(ModuleGroup, campaign.group_id)
        if not group:
            group = ModuleGroup(
                module_id=module.id,
                name=f"CE Campaign {campaign.id} Group",
            )
            db.session.add(group)
            db.session.flush()
            campaign.group_id = group.id

        # 2. Clear existing records in this group
        for record in group.records:
            db.session.delete(record)
        
        # Clear existing campaign targets
        CampaignTarget.query.filter_by(campaign_id=campaign.id).delete()
        db.session.commit()

        # 3. Create ModuleFields for each header
        fields_map = {}
        for h in headers:
            f_name = h.strip()
            field = ModuleField.query.filter_by(module_id=module.id, name=f_name).first()
            if not field:
                f_type = "phone" if f_name.lower() in _PHONE_KEYS else "string"
                field = ModuleField(
                    module_id=module.id,
                    group_id=group.id,
                    name=f_name,
                    field_type=f_type
                )
                db.session.add(field)
                db.session.flush()
            fields_map[f_name] = field.id

        # 4. Insert records and create CampaignTargets
        record_count = 0
        for row in reader:
            if not row or len(row) < len(headers):
                continue
            
            record = ModuleRecord(
                module_id=module.id,
                group_id=group.id,
            )
            db.session.add(record)
            db.session.flush()

            phone_val = ""
            for idx, h in enumerate(headers):
                val_str = row[idx].strip()
                if idx == phone_col_idx:
                    phone_val = val_str
                val_obj = ModuleRecordValue(
                    record_id=record.id,
                    field_id=fields_map[h],
                    value=val_str
                )
                db.session.add(val_obj)

            if phone_val:
                target = CampaignTarget(
                    campaign_id=campaign.id,
                    record_id=record.id,
                    status="queued",
                    call_attempts=0,
                    retry_count=0
                )
                db.session.add(target)
                record_count += 1

        db.session.commit()
        flash(f"Successfully uploaded {record_count} contacts for this campaign.", "success")
    except Exception as e:
        db.session.rollback()
        print(f"[CSV UPLOAD ERROR] {e}")
        flash(f"Failed to process CSV file: {str(e)}", "danger")

    return redirect(url_for("campaign_express.campaign_detail", cid=campaign.id))


@campaign_express_bp.route("/campaigns/<int:cid>/script", methods=["POST"])
@campaign_express_required
def campaign_script(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    if campaign.status in ("running", "completed"):
        flash("Cannot edit the script of a running or completed campaign.", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    content = request.form.get("content", "").strip()
    language = request.form.get("language", "English").strip()
    voice_gender = request.form.get("voice_gender", "female").strip()
    backup_enabled = "backup_enabled" in request.form
    backup_template = request.form.get("backup_template", "").strip()

    if not content:
        flash("Script content cannot be empty.", "danger")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    try:
        script = None
        if campaign.script_id:
            script = db.session.get(Script, campaign.script_id)
        if not script:
            script = Script(
                language=language,
                type=campaign.type,
                content=content,
                backup_enabled=backup_enabled,
                backup_template=backup_template,
                voice_gender=voice_gender,
            )
            db.session.add(script)
            db.session.flush()
            campaign.script_id = script.id
        else:
            script.content = content
            script.language = language
            script.voice_gender = voice_gender
            script.backup_enabled = backup_enabled
            script.backup_template = backup_template
            script.type = campaign.type

        db.session.commit()
        flash("Script configured successfully.", "success")
    except Exception as e:
        db.session.rollback()
        print(f"[SCRIPT SAVE ERROR] {e}")
        flash(f"Failed to save script: {str(e)}", "danger")

    return redirect(url_for("campaign_express.campaign_detail", cid=campaign.id))


@campaign_express_bp.route("/campaigns/<int:cid>/edit", methods=["GET", "POST"])
@campaign_express_required
def campaign_edit(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    if campaign.status in ("running", "completed"):
        flash("Cannot edit a running or completed campaign.", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    if request.method == "POST":
        campaign.name = request.form.get("name", campaign.name).strip()
        campaign.type = request.form.get("type", campaign.type)
        db.session.commit()
        flash("Campaign updated.", "success")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    return render_template("campaign_express/campaign_edit.html", campaign=campaign)


@campaign_express_bp.route("/campaigns/<int:cid>/delete", methods=["POST"])
@campaign_express_required
def campaign_delete(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    if campaign.status == "running":
        return jsonify({"success": False, "error": "Cannot delete a running campaign."}), 400

    db.session.delete(campaign)
    db.session.commit()
    flash("Campaign deleted.", "success")
    return redirect(url_for("campaign_express.campaigns"))


@campaign_express_bp.route("/campaigns/<int:cid>/duplicate", methods=["POST"])
@campaign_express_required
def campaign_duplicate(cid):
    original = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    copy = Campaign(
        name=f"{original.name} (Copy)",
        type=original.type,
        script_id=original.script_id,
        status="draft",
        campaign_express_user_id=current_user.id,
    )
    db.session.add(copy)
    db.session.commit()
    flash("Campaign duplicated as draft.", "success")
    return redirect(url_for("campaign_express.campaign_detail", cid=copy.id))


@campaign_express_bp.route("/campaigns/<int:cid>/archive", methods=["POST"])
@campaign_express_required
def campaign_archive(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()
    campaign.status = "archived"
    db.session.commit()
    flash("Campaign archived.", "success")
    return redirect(url_for("campaign_express.campaigns"))


# ─────────────────────────────────────────────────────────────────────────────
# CAMPAIGN EXECUTION — Verification Gate + Payment + Launch
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/campaigns/<int:cid>/launch", methods=["POST"])
@campaign_express_required
def campaign_launch(cid):
    """
    Execution gate:
      1. Check verification_status
      2. If not verified → redirect to verification boarding (saves campaign_id in session)
      3. If verified → check/create payment → execute campaign
    """
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    # ── Verification gate ──────────────────────────────────────────────────────
    if not current_user.is_verified:
        session["pending_campaign_id"] = cid
        flash("Please complete verification before launching campaigns.", "info")
        return redirect(url_for("campaign_express.verification"))

    # ── Check campaign is ready ────────────────────────────────────────────────
    if campaign.status not in ("draft", "ready", "waiting_payment"):
        flash("Campaign cannot be launched in its current state.", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    # ── Check targets exist ───────────────────────────────────────────────────
    target_count = CampaignTarget.query.filter_by(campaign_id=cid).count()
    if target_count == 0:
        flash("Please upload contacts before launching.", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    # ── Cost estimate ─────────────────────────────────────────────────────────
    COST_PER_CALL  = 1.50
    estimated_cost = round(target_count * COST_PER_CALL, 2)

    # ── Create pending payment ────────────────────────────────────────────────
    existing_payment = CampaignExpressPayment.query.filter_by(
        campaign_id=cid,
        user_id=current_user.id,
        status="completed",
    ).first()

    if not existing_payment:
        payment = CampaignExpressPayment(
            user_id     = current_user.id,
            campaign_id = cid,
            amount      = estimated_cost,
            status      = "pending",
        )
        db.session.add(payment)
        campaign.status = "waiting_payment"
        db.session.commit()

        flash(
            f"Estimated cost: ₹{estimated_cost:.2f} for {target_count} contacts. "
            f"Confirm payment to launch.",
            "info",
        )
        return redirect(url_for("campaign_express.campaign_pay", cid=cid))

    # Payment already confirmed — execute directly
    return _execute_campaign(campaign)


@campaign_express_bp.route("/campaigns/<int:cid>/pay", methods=["GET", "POST"])
@campaign_express_required
def campaign_pay(cid):
    from app.services.payment_gateway_service import PaymentGatewayService

    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()
    payment  = CampaignExpressPayment.query.filter_by(
        campaign_id=cid, user_id=current_user.id, status="pending"
    ).order_by(CampaignExpressPayment.created_at.desc()).first()

    if not payment:
        flash("No pending payment found for this campaign.", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    if request.method == "POST":
        payment_ref = request.form.get("payment_ref", f"CE-PAY-{uuid.uuid4().hex[:10].upper()}")
        payment.status       = "completed"
        payment.payment_ref  = payment_ref
        payment.completed_at = datetime.utcnow()
        campaign.status      = "ready"
        db.session.commit()
        flash("Payment confirmed! Launching campaign now.", "success")
        return _execute_campaign(campaign)

    from app.models.platform import PaymentMethod
    import json
    target_count = CampaignTarget.query.filter_by(campaign_id=cid).count()
    gateways = PaymentGatewayService.get_active_gateways()
    
    # Retrieve Dynamic UPI settings
    upi_method = PaymentMethod.query.filter_by(type="dynamic_upi", is_active=True).first()
    upi_config = {}
    if upi_method:
        try:
            upi_config = json.loads(upi_method.instructions)
        except Exception:
            pass

    return render_template(
        "campaign_express/payment_confirm.html",
        campaign=campaign,
        payment=payment,
        target_count=target_count,
        gateways=gateways,
        upi_config=upi_config
    )


def _execute_campaign(campaign):
    """
    Trigger campaign execution via existing CampaignExecutionService.
    Automatically allocates a platform pool number before starting.
    """
    from app.services.ce_number_allocator import CeNumberAllocator

    # ── Allocate a pool number ────────────────────────────────────────────────
    assigned_number = CeNumberAllocator.allocate(campaign.id)
    if not assigned_number:
        flash(
            "No communication numbers are currently available in the platform pool. "
            "Your campaign is queued and will start automatically when a number becomes free.",
            "warning",
        )
        campaign.status = "queued"
        db.session.commit()
        return redirect(url_for("campaign_express.campaign_detail", cid=campaign.id))

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        from app.services.campaign_runner import CampaignExecutionService
        campaign.status = "running"
        db.session.commit()
        CampaignExecutionService.start(current_app._get_current_object(), campaign.id)
        flash("Campaign is now running!", "success")
    except Exception as e:
        # Release the number back to pool on failure
        CeNumberAllocator.release(campaign.id)
        campaign.status = "ready"
        db.session.commit()
        flash(f"Failed to start campaign: {str(e)}", "danger")

    return redirect(url_for("campaign_express.campaign_detail", cid=campaign.id))


# ─────────────────────────────────────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/reports")
@campaign_express_required
def reports():
    # Reports = completed campaigns with delivery data
    completed = Campaign.query.filter_by(
        campaign_express_user_id=current_user.id,
        status="completed",
    ).order_by(Campaign.created_at.desc()).all()

    report_data = []
    for c in completed:
        logs    = DeliveryLog.query.filter_by(campaign_id=c.id).all()
        total   = len(logs)
        success = sum(1 for l in logs if l.status in ("completed", "sent", "delivered", "read"))
        report_data.append({
            "campaign": c,
            "total":    total,
            "success":  success,
            "rate":     round(success / total * 100, 1) if total > 0 else 0,
        })

    return render_template("campaign_express/reports.html", report_data=report_data)


@campaign_express_bp.route("/reports/<int:cid>")
@campaign_express_required
def report_detail(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    logs          = DeliveryLog.query.filter_by(campaign_id=cid).all()
    total_calls   = len(logs)
    connected     = sum(1 for l in logs if l.status in ("completed", "sent", "delivered", "read"))
    failed        = total_calls - connected
    completion_rt = round(connected / total_calls * 100, 1) if total_calls > 0 else 0

    # Duration from meta
    durations = [
        int(l.meta.get("duration_seconds", 0))
        for l in logs if l.meta and l.meta.get("duration_seconds")
    ]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0

    payment = CampaignExpressPayment.query.filter_by(
        campaign_id=cid, user_id=current_user.id, status="completed"
    ).first()

    return render_template(
        "campaign_express/report_detail.html",
        campaign=campaign,
        logs=logs,
        total_calls=total_calls,
        connected=connected,
        failed=failed,
        completion_rt=completion_rt,
        avg_duration=avg_duration,
        payment=payment,
    )


@campaign_express_bp.route("/reports/<int:cid>/export/csv")
@campaign_express_required
def report_export_csv(cid):
    from flask import Response
    import csv, io

    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()
    logs = DeliveryLog.query.filter_by(campaign_id=cid).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Recipient", "Channel", "Status", "Duration (s)", "Created At"])
    for l in logs:
        duration = l.meta.get("duration_seconds", "") if l.meta else ""
        writer.writerow([l.recipient, l.channel, l.status, duration, l.created_at])

    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=report_{cid}.csv"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/payments")
@campaign_express_required
def payments():
    all_payments = CampaignExpressPayment.query.filter_by(
        user_id=current_user.id
    ).order_by(CampaignExpressPayment.created_at.desc()).all()
    return render_template("campaign_express/payments.html", payments=all_payments)


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/profile", methods=["GET", "POST"])
@campaign_express_required
def profile():
    user = current_user

    if request.method == "POST":
        user.first_name       = request.form.get("first_name", user.first_name or "").strip()
        user.last_name        = request.form.get("last_name",  user.last_name  or "").strip()
        user.campaign_purpose = request.form.get("campaign_purpose", user.campaign_purpose)
        user.address_line1    = request.form.get("address_line1",    user.address_line1 or "").strip()
        user.address_line2    = request.form.get("address_line2",    user.address_line2 or "").strip()
        user.city             = request.form.get("city",             user.city          or "").strip()
        user.state            = request.form.get("state",            user.state         or "").strip()
        user.country          = request.form.get("country",          user.country       or "").strip()
        user.postal_code      = request.form.get("postal_code",      user.postal_code   or "").strip()

        photo_file = request.files.get("profile_photo")
        if photo_file and photo_file.filename:
            user.profile_photo = _save_upload(photo_file, "ce_profiles")

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("campaign_express.profile"))

    return render_template(
        "campaign_express/profile.html",
        user=user,
        purposes=CAMPAIGN_PURPOSE_OPTIONS,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SUPPORT, GUIDES
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/support")
@campaign_express_required
def support():
    return render_template("campaign_express/support.html")


@campaign_express_bp.route("/guides")
@campaign_express_required
def guides():
    return render_template("campaign_express/guides.html")


# ─────────────────────────────────────────────────────────────────────────────
# API — Verification Status
# ─────────────────────────────────────────────────────────────────────────────

@campaign_express_bp.route("/api/verification-status")
@campaign_express_required
def api_verification_status():
    return jsonify({
        "verification_status": current_user.verification_status,
        "is_verified":         current_user.is_verified,
        "label":               current_user.display_verification_label,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Records and Fields Management (Monochrome Worker-style CRM)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_logic(record, field):
    """Evaluates calculated or boolean logic for a record with safety checks."""
    try:
        meta = field.meta
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except:
                meta = {}

        if field.field_type == "calculated":
            formula = meta.get("formula", "") if meta else ""
            if not formula:
                return "0"

            vals = record.named_values
            for f_name in sorted(vals.keys(), key=len, reverse=True):
                f_val = vals[f_name]
                clean_val = str(f_val) if f_val is not None else "0"
                if not clean_val.replace(".", "", 1).isdigit():
                    clean_val = "0"
                formula = formula.replace(f"{{{f_name}}}", clean_val)

            allowed_chars = set("0123456789+-*/(). ")
            if not all(c in allowed_chars for c in formula):
                return "Invalid Formula"

            try:
                return str(eval(formula, {"__builtins__": None}, {}))
            except:
                return "Eval Error"

        elif field.field_type == "boolean":
            conditions = meta.get("conditions", []) if meta else []
            if not conditions:
                return "False"

            vals = record.named_values
            overall_result = True

            for i, cond in enumerate(conditions):
                f_name = cond.get("field")
                op = cond.get("operator")
                target = str(cond.get("value", ""))
                joiner = cond.get("joiner", "AND")

                actual = str(vals.get(f_name, ""))
                res = False

                try:
                    if op == "==":
                        res = actual == target
                    elif op == "!=":
                        res = actual != target
                    elif op == ">":
                        res = (
                            float(actual) > float(target)
                            if (
                                actual.replace(".", "", 1).isdigit()
                                and target.replace(".", "", 1).isdigit()
                            )
                            else False
                        )
                    elif op == "<":
                        res = (
                            float(actual) < float(target)
                            if (
                                actual.replace(".", "", 1).isdigit()
                                and target.replace(".", "", 1).isdigit()
                            )
                            else False
                        )
                    elif op == "contains":
                        res = target in actual
                except:
                    res = False

                if i == 0:
                    overall_result = res
                else:
                    if joiner == "AND":
                        overall_result = overall_result and res
                    else:
                        overall_result = overall_result or res

            return "True" if overall_result else "False"
    except Exception as e:
        current_app.logger.error(f"Logic evaluation error: {str(e)}")
        return "Error"

    return ""


def sync_campaign_target(campaign_id, record):
    """Creates or deletes a CampaignTarget for the record based on phone presence."""
    from app.services.campaign_runner import _extract_phone_from_record
    phone = _extract_phone_from_record(record)
    target = CampaignTarget.query.filter_by(campaign_id=campaign_id, record_id=record.id).first()
    
    if phone:
        if not target:
            target = CampaignTarget(
                campaign_id=campaign_id,
                record_id=record.id,
                status="queued",
                call_attempts=0,
                retry_count=0
            )
            db.session.add(target)
    else:
        if target:
            db.session.delete(target)


@campaign_express_bp.route("/campaigns/<int:cid>/records/add", methods=["POST"])
@campaign_express_required
def add_record(cid):
    from app.models.modules import ModuleField, ModuleRecord, ModuleRecordValue
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    mid = campaign.module_id
    group_id = campaign.group_id
    if not mid or not group_id:
        flash("Campaign module is not initialized.", "danger")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    record = ModuleRecord(module_id=mid, group_id=group_id)
    db.session.add(record)
    db.session.flush()

    fields = ModuleField.query.filter_by(module_id=mid, group_id=group_id).all()
    for f in fields:
        if f.field_type in ["calculated", "boolean"]:
            continue

        val_text = ""
        if f.field_type == "file":
            file = request.files.get(f"field_{f.id}")
            if file and file.filename:
                filename = secure_filename(file.filename)
                filename = f"rec_{record.id}_{filename}"
                file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                val_text = filename
        else:
            val_text = request.form.get(f"field_{f.id}")

        if val_text:
            if f.is_unique:
                existing = (
                    ModuleRecordValue.query.filter_by(field_id=f.id, value=val_text)
                    .join(ModuleRecord)
                    .filter(ModuleRecord.group_id == group_id)
                    .first()
                )
                if existing:
                    db.session.rollback()
                    flash(f"Duplicate detected: {val_text} for unique field '{f.name}'", "danger")
                    return redirect(url_for("campaign_express.campaign_detail", cid=cid))

            val = ModuleRecordValue(record_id=record.id, field_id=f.id, value=val_text)
            db.session.add(val)

    db.session.flush()
    sync_campaign_target(campaign.id, record)
    db.session.commit()
    flash("Entry added successfully", "success")
    return redirect(url_for("campaign_express.campaign_detail", cid=cid))


@campaign_express_bp.route("/api/campaigns/<int:cid>/records/<int:rid>")
@campaign_express_required
def get_record_api(cid, rid):
    from app.models.modules import ModuleField, ModuleRecord
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    r = db.get_or_404(ModuleRecord, rid)
    if r.module_id != campaign.module_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    fields = ModuleField.query.filter_by(module_id=campaign.module_id, group_id=r.group_id).all()
    values = {v.field_id: v.value for v in r.values}
    
    for f in fields:
        if f.field_type in ["calculated", "boolean"]:
            values[f.id] = evaluate_logic(r, f)

    return jsonify(
        {
            "success": True,
            "fields": [
                {"id": f.id, "name": f.name, "type": f.field_type, "options": f.options}
                for f in fields
            ],
            "values": values,
        }
    )


@campaign_express_bp.route("/api/campaigns/<int:cid>/records/<int:rid>/update", methods=["POST"])
@campaign_express_required
def update_record_api(cid, rid):
    from app.models.modules import ModuleField, ModuleRecord, ModuleRecordValue
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    r = db.get_or_404(ModuleRecord, rid)
    if r.module_id != campaign.module_id:
        flash("Access denied", "danger")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    fields = ModuleField.query.filter_by(module_id=campaign.module_id, group_id=r.group_id).all()
    for f in fields:
        if f.field_type in ["calculated", "boolean"]:
            continue

        val_text = ""
        if f.field_type == "file":
            file = request.files.get(f"field_{f.id}")
            if file and file.filename:
                filename = secure_filename(file.filename)
                filename = f"rec_{rid}_{filename}"
                file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                val_text = filename
            else:
                continue
        else:
            val_text = request.form.get(f"field_{f.id}")

        val_obj = ModuleRecordValue.query.filter_by(record_id=rid, field_id=f.id).first()

        if f.is_unique and val_text:
            existing = (
                ModuleRecordValue.query.filter(
                    ModuleRecordValue.field_id == f.id,
                    ModuleRecordValue.value == val_text,
                    ModuleRecordValue.record_id != rid,
                )
                .join(ModuleRecord)
                .filter(ModuleRecord.module_id == campaign.module_id, ModuleRecord.group_id == r.group_id)
                .first()
            )
            if existing:
                flash(f"Update failed: '{val_text}' is already registered for unique field '{f.name}'.", "danger")
                return redirect(url_for("campaign_express.campaign_detail", cid=cid))

        if val_obj:
            val_obj.value = val_text
        else:
            val_obj = ModuleRecordValue(record_id=rid, field_id=f.id, value=val_text)
            db.session.add(val_obj)

    db.session.flush()
    sync_campaign_target(campaign.id, r)
    db.session.commit()
    flash("Record updated successfully", "success")
    return redirect(url_for("campaign_express.campaign_detail", cid=cid))


@campaign_express_bp.route("/api/campaigns/<int:cid>/records/<int:rid>/delete", methods=["POST"])
@campaign_express_required
def delete_record_api(cid, rid):
    from app.models.modules import ModuleRecord
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    r = db.get_or_404(ModuleRecord, rid)
    if r.module_id != campaign.module_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    db.session.delete(r)
    db.session.commit()
    return jsonify({"success": True})


@campaign_express_bp.route("/api/campaigns/<int:cid>/records/bulk-delete", methods=["POST"])
@campaign_express_required
def bulk_delete_records(cid):
    from app.models.modules import ModuleRecord
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    data = request.get_json()
    record_ids = data.get("record_ids", [])

    if not record_ids:
        return jsonify({"success": False, "error": "No records selected"}), 400

    try:
        records = (
            ModuleRecord.query.filter(ModuleRecord.id.in_(record_ids))
            .filter_by(module_id=campaign.module_id)
            .all()
        )

        count = len(records)
        for r in records:
            db.session.delete(r)

        db.session.commit()
        return jsonify({"success": True, "count": count})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@campaign_express_bp.route("/api/campaigns/<int:cid>/fields", methods=["GET", "POST"])
@campaign_express_required
def campaign_fields_api(cid):
    from app.models.modules import ModuleField
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    mid = campaign.module_id
    group_id = campaign.group_id

    if request.method == "POST":
        data = request.get_json() or {}
        action = data.get("action")

        if action == "add":
            name = data.get("name")
            field_type = data.get("field_type")
            is_unique = data.get("is_unique", False)
            meta = data.get("meta", {})
            f = ModuleField(
                module_id=mid,
                group_id=group_id,
                name=name,
                field_type=field_type,
                is_unique=is_unique,
                meta=meta,
            )
            db.session.add(f)
        elif action == "update":
            fid = data.get("field_id")
            f = db.session.get(ModuleField, fid)
            if f and f.module_id == mid:
                f.name = data.get("name", f.name)
                f.field_type = data.get("field_type", f.field_type)
                f.is_unique = data.get("is_unique", f.is_unique)
                f.meta = data.get("meta", f.meta)
        elif action == "delete":
            fid = data.get("field_id")
            f = db.session.get(ModuleField, fid)
            if f and f.module_id == mid:
                db.session.delete(f)

        db.session.commit()
        return jsonify({"success": True})

    fields = ModuleField.query.filter_by(module_id=mid, group_id=group_id).all()
    return jsonify(
        {
            "success": True,
            "fields": [
                {"id": f.id, "name": f.name, "type": f.field_type, "is_unique": f.is_unique, "meta": f.meta}
                for f in fields
            ],
        }
    )


@campaign_express_bp.route("/api/campaigns/<int:cid>/fields/<int:fid>/delete", methods=["POST"])
@campaign_express_required
def delete_field_api(cid, fid):
    from app.models.modules import ModuleField
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    f = db.get_or_404(ModuleField, fid)
    if f.module_id != campaign.module_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    db.session.delete(f)
    db.session.commit()
    return jsonify({"success": True})


@campaign_express_bp.route("/campaigns/<int:cid>/import", methods=["POST"])
@campaign_express_required
def import_records(cid):
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected", "danger")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    import csv
    import io
    from app.models.modules import ModuleField, ModuleRecord, ModuleRecordValue
    from app.services.campaign_runner import _PHONE_KEYS

    try:
        stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
        reader = csv.reader(stream)
        headers = [h.strip() for h in next(reader, [])]

        if not headers:
            flash("The CSV file is empty.", "danger")
            return redirect(url_for("campaign_express.campaign_detail", cid=cid))

        phone_col_idx = -1
        for idx, h in enumerate(headers):
            if h.lower() in _PHONE_KEYS:
                phone_col_idx = idx
                break

        if phone_col_idx == -1:
            phone_col_idx = 0

        mid = campaign.module_id
        group_id = campaign.group_id

        fields_map = {}
        for h in headers:
            f_name = h.strip()
            field = ModuleField.query.filter_by(module_id=mid, name=f_name).first()
            if not field:
                f_type = "phone" if f_name.lower() in _PHONE_KEYS else "string"
                field = ModuleField(
                    module_id=mid,
                    group_id=group_id,
                    name=f_name,
                    field_type=f_type
                )
                db.session.add(field)
                db.session.flush()
            fields_map[f_name] = field.id

        for row in reader:
            if not row or len(row) < len(headers):
                continue
            
            record = ModuleRecord(module_id=mid, group_id=group_id)
            db.session.add(record)
            db.session.flush()

            for idx, h in enumerate(headers):
                val_str = row[idx].strip()
                val_obj = ModuleRecordValue(
                    record_id=record.id,
                    field_id=fields_map[h],
                    value=val_str
                )
                db.session.add(val_obj)

            db.session.flush()
            sync_campaign_target(campaign.id, record)

        db.session.commit()
        flash("Data imported successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {str(e)}", "danger")

    return redirect(url_for("campaign_express.campaign_detail", cid=cid))


@campaign_express_bp.route("/campaigns/<int:cid>/export/<string:format>")
@campaign_express_required
def export_records(cid, format):
    from app.models.modules import ModuleField, ModuleRecord
    campaign = Campaign.query.filter_by(
        id=cid, campaign_express_user_id=current_user.id
    ).first_or_404()

    mid = campaign.module_id
    group_id = campaign.group_id
    if not mid or not group_id:
        flash("No data to export", "warning")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))

    fields = ModuleField.query.filter_by(module_id=mid, group_id=group_id).order_by(ModuleField.id).all()
    records = ModuleRecord.query.filter_by(module_id=mid, group_id=group_id).order_by(ModuleRecord.id.desc()).all()

    import csv
    import io
    from flask import Response

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([f.name for f in fields])
        
        for r in records:
            row = []
            f_vals = r.field_values
            for f in fields:
                if f.field_type in ["calculated", "boolean"]:
                    row.append(evaluate_logic(r, f))
                else:
                    row.append(f_vals.get(f.id, ""))
            writer.writerow(row)
            
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=campaign_{cid}_export.csv"}
        )
    else:
        flash("Excel export not configured. Export as CSV instead.", "info")
        return redirect(url_for("campaign_express.campaign_detail", cid=cid))
