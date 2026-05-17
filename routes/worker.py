from flask import (
    request,
    redirect,
    url_for,
    flash,
    render_template,
    jsonify,
    current_app,
    Blueprint,
    session,
)
from flask_login import current_user, login_required, login_user, logout_user
from models.models import (
    db,
    Module,
    ModuleField,
    ModuleRecord,
    Campaign,
    DeliveryLog,
    OrganizationUser,
    ChangeRequest,
    PlatformNotification,
    ModuleRecordValue,
    ModuleGroup,
    Subscription,
)
from utils.decorators import worker_required, active_subscription_required
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
import json
import re

worker_bp = Blueprint("worker", __name__, url_prefix="/worker")
from datetime import datetime, timedelta
import os
import time
import threading


@worker_bp.route("/dashboard")
@worker_required
@active_subscription_required
def dashboard():
    org_id = current_user.organization_id
    modules = Module.query.filter_by(organization_id=org_id).all()

    # Base stats
    total_modules = len(modules)
    m_ids = [m.id for m in modules]

    total_records = (
        ModuleRecord.query.filter(ModuleRecord.module_id.in_(m_ids)).count()
        if m_ids
        else 0
    )
    active_campaigns = (
        Campaign.query.filter(
            Campaign.module_id.in_(m_ids), Campaign.status == "running"
        ).count()
        if m_ids
        else 0
    )

    # Success Rate Calculation
    campaign_ids = (
        [c.id for c in Campaign.query.filter(Campaign.module_id.in_(m_ids)).all()]
        if m_ids
        else []
    )
    total_logs = (
        DeliveryLog.query.filter(DeliveryLog.campaign_id.in_(campaign_ids)).count()
        if campaign_ids
        else 0
    )
    success_logs = (
        DeliveryLog.query.filter(
            DeliveryLog.campaign_id.in_(campaign_ids),
            DeliveryLog.status.in_(["sent", "delivered", "read", "completed"]),
        ).count()
        if campaign_ids
        else 0
    )

    success_rate = round((success_logs / total_logs * 100), 1) if total_logs > 0 else 0

    # Module enrichment (Real Data)
    for m in modules:
        m.record_count = ModuleRecord.query.filter_by(module_id=m.id).count()
        m.campaign_count = Campaign.query.filter_by(module_id=m.id).count()
        last_record = (
            ModuleRecord.query.filter_by(module_id=m.id)
            .order_by(ModuleRecord.created_at.desc())
            .first()
        )
        m.last_activity = (
            last_record.created_at.strftime("%d %b %Y")
            if last_record
            else "No activity"
        )

    return render_template(
        "worker/dashboard.html",
        modules=modules,
        total_modules=total_modules,
        active_campaigns=active_campaigns,
        total_records=total_records,
        success_rate=success_rate,
        current_user=current_user,
    )


@worker_bp.route("/api/worker-analytics")
@worker_required
def worker_analytics():
    org_id = current_user.organization_id
    module_id = request.args.get("module_id")

    if module_id:
        m_ids = [int(module_id)]
        m_obj = db.session.get(Module, module_id)
        m_name = m_obj.name if m_obj else "Unknown"
    else:
        m_ids = [m.id for m in Module.query.filter_by(organization_id=org_id).all()]
        m_name = "All Modules"

    if not m_ids:
        return jsonify(
            {
                "trend": {"labels": [], "data": []},
                "distribution": {"labels": [], "data": []},
            }
        )

    # Performance Trend (Last 7 Days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    trend_query = (
        db.session.query(
            db.func.date(DeliveryLog.created_at), db.func.count(DeliveryLog.id)
        )
        .join(Campaign)
        .filter(Campaign.module_id.in_(m_ids), DeliveryLog.created_at >= seven_days_ago)
        .group_by(db.func.date(DeliveryLog.created_at))
        .all()
    )

    # Distribution (Records per Module)
    dist_query = (
        db.session.query(Module.name, db.func.count(ModuleRecord.id))
        .join(ModuleRecord)
        .filter(Module.id.in_(m_ids))
        .group_by(Module.name)
        .all()
    )

    return jsonify(
        {
            "module_name": m_name,
            "trend": {
                "labels": [
                    t[0].strftime("%d %b") if hasattr(t[0], "strftime") else str(t[0])
                    for t in trend_query
                ],
                "data": [t[1] for t in trend_query],
            },
            "distribution": {
                "labels": [d[0] for d in dist_query],
                "data": [d[1] for d in dist_query],
            },
        }
    )


@worker_bp.route("/modules")
@worker_required
def modules():
    # Show only the modules present
    modules = Module.query.filter_by(organization_id=current_user.organization_id).all()
    return render_template("worker/modules_list.html", modules=modules)


@worker_bp.route("/modules/create", methods=["GET", "POST"])
@worker_required
@active_subscription_required
def create_module():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")

        if not name:
            flash("Module name is required", "danger")
            return render_template("worker/module_create.html")

        new_module = Module(
            organization_id=current_user.organization_id,
            name=name,
            description=description,
            status="active",
            created_by_id=current_user.id,
        )
        db.session.add(new_module)
        db.session.commit()

        ChangeRequest.log(
            new_module.organization_id,
            current_user.id,
            "Module Creation",
            new_val=f"New module '{name}' created",
        )

        flash(f"Module '{name}' created successfully!", "success")
        return redirect(url_for("worker.manage_module", mid=new_module.id))

    return render_template("worker/module_create.html")


@worker_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        selected_org_id = request.form.get("organization_id")
        matching_users = OrganizationUser.query.filter_by(email=email).all()
        valid_users = [u for u in matching_users if u.check_password(password)]
        if not valid_users:
            flash("Invalid credentials", "danger")
            return render_template("auth/worker_login.html")
        if selected_org_id:
            user = OrganizationUser.query.filter_by(
                email=email, organization_id=selected_org_id
            ).first()
            if user and user.check_password(password):
                sub = Subscription.query.filter_by(
                    organization_id=user.organization_id
                ).first()
                if (
                    not sub
                    or sub.status == "inactive"
                    or (
                        sub.expires_at
                        and datetime.utcnow() > sub.expires_at + timedelta(days=3)
                    )
                ):
                    flash(
                        "Organization services are suspended or a subscription is required.",
                        "danger",
                    )
                    return render_template("auth/worker_login.html")
                user.login_count = (user.login_count or 0) + 1
                user.last_login = datetime.utcnow()
                db.session.commit()
                ChangeRequest.log(
                    user.organization_id,
                    user.id,
                    "Worker Login",
                    new_val=f"Worker session started from {request.remote_addr}",
                )
                login_user(user)
                return redirect(url_for("worker.dashboard"))
        if len(valid_users) == 1:
            user = valid_users[0]
            sub = Subscription.query.filter_by(
                organization_id=user.organization_id
            ).first()
            if (
                not sub
                or sub.status == "inactive"
                or (
                    sub.expires_at
                    and datetime.utcnow() > sub.expires_at + timedelta(days=3)
                )
            ):
                flash(
                    "Organization services are suspended or a subscription is required.",
                    "danger",
                )
                return render_template("auth/worker_login.html")
            user.login_count = (user.login_count or 0) + 1
            user.last_login = datetime.utcnow()
            db.session.commit()
            ChangeRequest.log(
                user.organization_id,
                user.id,
                "Worker Login",
                new_val=f"Worker direct login from {request.remote_addr}",
            )
            login_user(user)
            return redirect(url_for("worker.dashboard"))
        return render_template(
            "auth/select_org.html",
            matching_users=valid_users,
            email=email,
            password=password,
        )
    return render_template("auth/worker_login.html")


@worker_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))


@worker_bp.route("/modules/<int:mid>/manage")
@worker_required
def manage_module(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    fields = ModuleField.query.filter_by(module_id=mid).order_by(ModuleField.id).all()
    records = (
        ModuleRecord.query.filter_by(module_id=mid)
        .order_by(ModuleRecord.created_at.desc())
        .all()
    )

    # Enrich records with calculated/boolean values
    for r in records:
        r.computed_values = {}
        # Pre-fetch values to avoid multiple property calls
        f_vals = r.field_values
        for f in fields:
            if f.field_type in ["calculated", "boolean"]:
                r.computed_values[f.id] = evaluate_logic(r, f)
            else:
                r.computed_values[f.id] = f_vals.get(f.id, "-")

    return render_template(
        "worker/module_manage.html", module=m, fields=fields, records=records
    )


@worker_bp.route("/api/recent-activities")
@worker_required
def recent_activities():
    activities = (
        ChangeRequest.query.filter_by(organization_id=current_user.organization_id)
        .order_by(ChangeRequest.created_at.desc())
        .limit(10)
        .all()
    )
    return jsonify(
        [
            {
                "id": a.id,
                "actor": a.user.full_name if a.user else "System",
                "action": a.field_name,
                "details": a.new_value,
                "timestamp": a.created_at.strftime("%H:%M %p"),
            }
            for a in activities
        ]
    )


@worker_bp.route("/api/modules/<int:mid>/update", methods=["POST"])
@worker_required
def update_module(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    data = request.get_json()
    new_name = data.get("name")

    if not new_name:
        return jsonify({"success": False, "error": "Name is required"}), 400

    old_name = m.name
    m.name = new_name
    db.session.commit()

    # Log activity
    ChangeRequest.log(
        m.organization_id,
        current_user.id,
        "Module Update",
        new_val=f"Module '{old_name}' renamed to '{new_name}'",
    )

    return jsonify({"success": True})


@worker_bp.route("/profile", methods=["GET", "POST"])
@worker_required
def profile():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        phone = request.form.get("phone")

        current_user.full_name = full_name
        current_user.phone = phone
        db.session.commit()

        flash("Profile updated successfully", "success")
        return redirect(url_for("worker.profile"))

    return render_template("worker/profile.html", user=current_user)


@worker_bp.route("/preferences", methods=["GET", "POST"])
@worker_required
def preferences():
    if request.method == "POST":
        # Placeholder for preferences update logic
        flash("Preferences updated successfully", "success")
        return redirect(url_for("worker.preferences"))

    return render_template("worker/preferences.html", user=current_user)


@worker_bp.route("/reports")
@worker_required
def reports():
    return render_template("worker/reports.html")


@worker_bp.route("/modules/<int:mid>")
@worker_required
def module_detail(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))
    return render_template("worker/module_detail.html", module=m, fields=m.fields)


# Authentication & Recovery Routes
@worker_bp.route("/google-auth")
def google_auth():
    import urllib.parse

    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    redirect_uri = url_for("main.google_callback", _external=True)
    scope = "openid email profile"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "select_account",
    }
    google_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    )
    return redirect(google_url)


@worker_bp.route("/oauth-select-org", methods=["GET", "POST"])
def oauth_select_org():
    email = session.get("oauth_email")
    if not email:
        return redirect(url_for("worker.login"))

    matching_users = OrganizationUser.query.filter_by(email=email).all()

    if request.method == "POST":
        org_id = request.form.get("organization_id")
        user = OrganizationUser.query.filter_by(
            email=email, organization_id=org_id
        ).first()
        if user:
            sub = Subscription.query.filter_by(
                organization_id=user.organization_id
            ).first()
            if (
                not sub
                or sub.status == "inactive"
                or (
                    sub.expires_at
                    and datetime.utcnow() > sub.expires_at + timedelta(days=3)
                )
            ):
                flash(
                    "Organization services are suspended or a subscription is required.",
                    "danger",
                )
                return redirect(url_for("worker.login"))
            login_user(user)
            session.pop("oauth_email", None)
            return redirect(url_for("worker.dashboard"))

    return render_template(
        "auth/oauth_select_org.html", matching_users=matching_users, email=email
    )


@worker_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        new_password = request.form.get("new_password")

        user = OrganizationUser.query.filter_by(email=email, role="worker").first()
        if not user:
            flash("No worker account found with this email address.", "danger")
            return render_template(
                "auth/forgot_password.html",
                forgot_url=url_for("worker.forgot_password"),
                login_url=url_for("worker.login"),
                email_label="Registered Worker Email",
                email_placeholder="worker@company.com",
            )

        pw_hash = generate_password_hash(new_password)

        req = ChangeRequest(
            organization_id=user.organization_id,
            user_id=user.id,
            field_name="password_reset",
            old_value="[hidden]",
            new_value=pw_hash,
            status="pending",
        )
        db.session.add(req)

        notif = PlatformNotification(
            organization_id=user.organization_id,
            type="info_change",
            title="Worker Password Reset Request",
            message=f"Worker ({email}) has requested a password reset. Please review and approve.",
            link=url_for("admin.pending_changes"),
        )
        db.session.add(notif)
        db.session.commit()
        return redirect(url_for("worker.forgot_password_submitted"))

    return render_template(
        "auth/forgot_password.html",
        forgot_url=url_for("worker.forgot_password"),
        login_url=url_for("worker.login"),
        email_label="Registered Worker Email",
        email_placeholder="worker@company.com",
    )


@worker_bp.route("/forgot-password/submitted")
def forgot_password_submitted():
    return render_template("auth/password_reset_submitted.html", portal="worker")


# Record Management Routes
@worker_bp.route("/modules/<int:mid>/records/add", methods=["POST"])
@worker_required
def add_record(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    # Create the record
    record = ModuleRecord(module_id=mid, created_by_id=current_user.id)
    db.session.add(record)
    db.session.flush()  # Get the record ID

    # Add values
    fields = ModuleField.query.filter_by(module_id=mid).all()
    for f in fields:
        if f.field_type in ["calculated", "boolean"]:
            continue

        val_text = ""
        if f.field_type == "file":
            file = request.files.get(f"field_{f.id}")
            if file and file.filename:
                filename = secure_filename(file.filename)
                # Prefix with record ID to avoid collisions
                filename = f"rec_{record.id}_{filename}"
                file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                val_text = filename
        else:
            val_text = request.form.get(f"field_{f.id}")

        if val_text:
            # Uniqueness check
            if f.is_unique:
                existing = (
                    ModuleRecordValue.query.filter_by(field_id=f.id, value=val_text)
                    .join(ModuleRecord)
                    .filter(ModuleRecord.module_id == mid)
                    .first()
                )
                if existing:
                    db.session.rollback()
                    flash(
                        f"Duplicate entry detected: '{val_text}' is already registered for '{f.name}'.",
                        "danger",
                    )
                    return redirect(url_for("worker.manage_module", mid=mid))

            val = ModuleRecordValue(record_id=record.id, field_id=f.id, value=val_text)
            db.session.add(val)

    db.session.commit()
    flash("Record added successfully", "success")
    return redirect(url_for("worker.manage_module", mid=mid))


@worker_bp.route("/api/records/<int:rid>")
@worker_required
def get_record_api(rid):
    r = db.get_or_404(ModuleRecord, rid)
    m = db.session.get(Module, r.module_id)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    fields = ModuleField.query.filter_by(module_id=m.id).all()
    values = {v.field_id: v.value for v in r.values}

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


@worker_bp.route("/api/records/<int:rid>/update", methods=["POST"])
@worker_required
def update_record_api(rid):
    r = db.get_or_404(ModuleRecord, rid)
    m = db.session.get(Module, r.module_id)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    # Update values
    fields = ModuleField.query.filter_by(module_id=m.id).all()
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
                # Keep existing file if no new file uploaded
                continue
        else:
            val_text = request.form.get(f"field_{f.id}")

        # Find or create value
        val_obj = ModuleRecordValue.query.filter_by(
            record_id=rid, field_id=f.id
        ).first()

        # Uniqueness check
        if f.is_unique and val_text:
            existing = (
                ModuleRecordValue.query.filter(
                    ModuleRecordValue.field_id == f.id,
                    ModuleRecordValue.value == val_text,
                    ModuleRecordValue.record_id != rid,
                )
                .join(ModuleRecord)
                .filter(ModuleRecord.module_id == m.id)
                .first()
            )
            if existing:
                flash(
                    f"Update failed: '{val_text}' is already registered for '{f.name}'.",
                    "danger",
                )
                return redirect(url_for("worker.manage_module", mid=m.id))

        if val_obj:
            val_obj.value = val_text
        else:
            val_obj = ModuleRecordValue(record_id=rid, field_id=f.id, value=val_text)
            db.session.add(val_obj)

    db.session.commit()
    flash("Record updated successfully", "success")
    return redirect(url_for("worker.manage_module", mid=m.id))


@worker_bp.route("/api/records/<int:rid>/delete", methods=["POST"])
@worker_required
def delete_record_api(rid):
    r = db.get_or_404(ModuleRecord, rid)
    m = db.session.get(Module, r.module_id)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    db.session.delete(r)
    db.session.commit()
    return jsonify({"success": True})


@worker_bp.route("/api/records/bulk-delete", methods=["POST"])
@worker_required
def bulk_delete_records():
    data = request.get_json()
    record_ids = data.get("record_ids", [])

    if not record_ids:
        return jsonify({"success": False, "error": "No records selected"}), 400

    try:
        # Delete only records belonging to the user's organization
        records = (
            ModuleRecord.query.filter(ModuleRecord.id.in_(record_ids))
            .join(Module)
            .filter(Module.organization_id == current_user.organization_id)
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


# Field Management Routes
@worker_bp.route("/modules/<int:mid>/fields/add", methods=["POST"])
@worker_required
def add_field(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    name = request.form.get("name")
    field_type = request.form.get("field_type", "text")
    is_unique = request.form.get("is_unique") == "true"

    if not name:
        flash("Field name is required", "danger")
        return redirect(request.referrer)

    f = ModuleField(
        module_id=mid, name=name, field_type=field_type, is_unique=is_unique
    )
    db.session.add(f)
    db.session.commit()
    flash(f"Field '{name}' added successfully", "success")
    return redirect(request.referrer)


@worker_bp.route("/api/fields/<int:fid>/delete", methods=["POST"])
@worker_required
def delete_field(fid):
    f = db.get_or_404(ModuleField, fid)
    m = db.session.get(Module, f.module_id)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    db.session.delete(f)
    db.session.commit()
    return jsonify({"success": True})


@worker_bp.route("/api/modules/<int:mid>/fields", methods=["GET", "POST"])
@worker_required
def module_fields_api(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    if request.method == "POST":
        data = request.get_json()
        action = data.get("action")  # add, update, delete

        if action == "add":
            name = data.get("name")
            field_type = data.get("field_type")
            is_unique = data.get("is_unique", False)
            meta = data.get("meta", {})
            f = ModuleField(
                module_id=mid,
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

    fields = ModuleField.query.filter_by(module_id=mid).all()
    return jsonify(
        {
            "success": True,
            "fields": [
                {"id": f.id, "name": f.name, "type": f.field_type, "meta": f.meta}
                for f in fields
            ],
        }
    )


@worker_bp.route("/modules/<int:mid>/import", methods=["POST"])
@worker_required
def import_records(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    file = request.files.get("file")
    if not file:
        flash("No file uploaded", "danger")
        return redirect(request.referrer)

    filename = secure_filename(file.filename)
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)

        # Get fields and identify unique ones
        fields = ModuleField.query.filter_by(module_id=mid).all()
        field_map = {f.name.lower(): f for f in fields}
        unique_fields = [f for f in fields if f.is_unique]

        import_count = 0
        skipped_count = 0

        for _, row in df.iterrows():
            # Check for duplicates before creating record
            is_duplicate = False
            for f in unique_fields:
                val = (
                    str(row[f.name])
                    if f.name in row and pd.notnull(row[f.name])
                    else ""
                )
                if val:
                    existing = (
                        ModuleRecordValue.query.filter_by(field_id=f.id, value=val)
                        .join(ModuleRecord)
                        .filter(ModuleRecord.module_id == mid)
                        .first()
                    )
                    if existing:
                        is_duplicate = True
                        break

            if is_duplicate:
                skipped_count += 1
                continue

            record = ModuleRecord(module_id=mid, created_by_id=current_user.id)
            db.session.add(record)
            db.session.flush()

            for col in df.columns:
                f_obj = field_map.get(col.lower())
                if f_obj:
                    val = str(row[col]) if pd.notnull(row[col]) else ""
                    db.session.add(
                        ModuleRecordValue(
                            record_id=record.id, field_id=f_obj.id, value=val
                        )
                    )
            import_count += 1

        db.session.commit()
        msg = f"Successfully imported {import_count} records"
        if skipped_count > 0:
            msg += f" ({skipped_count} duplicates skipped)"
        flash(msg, "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {str(e)}", "danger")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

    return redirect(url_for("worker.manage_module", mid=mid))


@worker_bp.route("/modules/<int:mid>/export/<string:format>")
@worker_required
def export_records(mid, format):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    fields = ModuleField.query.filter_by(module_id=mid).all()
    records = ModuleRecord.query.filter_by(module_id=mid).all()

    data = []
    for r in records:
        row = {"Date Created": r.created_at.strftime("%Y-%m-%d %H:%M")}
        vals = r.field_values
        for f in fields:
            row[f.name] = vals.get(f.id, "")
        data.append(row)

    df = pd.DataFrame(data)

    from flask import make_response
    import io

    if format == "csv":
        output = io.StringIO()
        df.to_csv(output, index=False)
        response = make_response(output.getvalue())
        response.headers[
            "Content-Disposition"
        ] = f"attachment; filename={m.name}_export.csv"
        response.headers["Content-type"] = "text/csv"
    else:  # excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Records")
        response = make_response(output.getvalue())
        response.headers[
            "Content-Disposition"
        ] = f"attachment; filename={m.name}_export.xlsx"
        response.headers[
            "Content-type"
        ] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return response


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

            # Replace {field_name} with actual value
            vals = record.named_values
            # Sort keys by length descending to avoid partial replacements (e.g., {name} vs {name_long})
            for f_name in sorted(vals.keys(), key=len, reverse=True):
                f_val = vals[f_name]
                # Ensure f_val is a number-like string if possible, else 0
                clean_val = str(f_val) if f_val is not None else "0"
                if not clean_val.replace(".", "", 1).isdigit():
                    clean_val = "0"
                formula = formula.replace(f"{{{f_name}}}", clean_val)

            # Basic math eval with restricted builtins
            # We only allow basic arithmetic
            allowed_chars = set("0123456789+-*/(). ")
            if not all(c in allowed_chars for c in formula):
                return "Invalid Formula"

            try:
                # Use a safe eval-like approach for basic math
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
