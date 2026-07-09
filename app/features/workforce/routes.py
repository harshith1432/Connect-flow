import sys
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
from app.models import (
    Module,
    ModuleField,
    ModuleRecord,
    Campaign,
    CampaignTarget,
    DeliveryLog,
    OrganizationUser,
    ChangeRequest,
    PlatformNotification,
    ModuleRecordValue,
    ModuleGroup,
    Subscription,
    Script,
    CommunicationNumber,
)
from app.services.campaign_runner import CampaignExecutionService
from app.extensions import db, csrf
from app.core.decorators import worker_required, active_subscription_required
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
import json
import re
from datetime import datetime, timedelta
import os
import time
import asyncio
import uuid
import csv
import io

worker_bp = Blueprint(
    "worker",
    __name__,
    url_prefix="/worker",
    template_folder="templates",
)


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
        m.group_count = ModuleGroup.query.filter_by(module_id=m.id).count()
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

    total_records = db.session.query(db.func.count(ModuleRecord.id)).filter(ModuleRecord.module_id.in_(m_ids)).scalar() or 0
    total_logs = DeliveryLog.query.join(Campaign).filter(Campaign.module_id.in_(m_ids)).count()
    success_logs = DeliveryLog.query.join(Campaign).filter(
        Campaign.module_id.in_(m_ids),
        DeliveryLog.status.in_(["sent", "delivered", "read", "completed"])
    ).count()
    success_rate = round((success_logs / total_logs * 100), 1) if total_logs > 0 else 0

    return jsonify(
        {
            "module_name": m_name,
            "total_attempts": total_logs,
            "success_rate": success_rate,
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

        # Check subscription and enforce module limits
        from app.models import Subscription
        sub = Subscription.query.filter_by(
            organization_id=current_user.organization_id
        ).first()
        
        from app.core.constants import PLAN_LIMITS
        plan_name = (sub.plan or "Free Trial").lower() if sub else "free trial"
        plan_limits = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["free trial"])
        
        current_modules_count = Module.query.filter_by(
            organization_id=current_user.organization_id
        ).count()
        
        if current_modules_count >= plan_limits["modules"]:
            flash(
                f"Your organization has reached the plan limit of {plan_limits['modules']} custom CRM modules. Please upgrade your subscription plan to create more.",
                "danger"
            )
            return redirect(url_for("worker.modules"))

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
        return redirect(url_for("worker.manage_groups", mid=new_module.id, **request.args))

    return render_template("worker/module_create.html")


@worker_bp.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("main.login", **request.args))


@worker_bp.route("/logout")
@login_required
def logout():
    from app.security.session_manager import SessionManager

    SessionManager.logout_and_clean()
    return redirect(url_for("main.index"))


@worker_bp.route("/modules/<int:mid>/manage")
@worker_required
def manage_module(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    # ── Group filter: if ?group=<id> is present, load only that group's records ──
    active_group = None
    group_id = request.args.get("group", type=int)
    if group_id:
        active_group = ModuleGroup.query.filter_by(id=group_id, module_id=mid).first()

    if active_group:
        fields = ModuleField.query.filter_by(module_id=mid, group_id=group_id).order_by(ModuleField.id).all()
        records = (
            ModuleRecord.query.filter_by(module_id=mid, group_id=group_id)
            .order_by(ModuleRecord.created_at.desc())
            .all()
        )
    else:
        fields = ModuleField.query.filter_by(module_id=mid, group_id=None).order_by(ModuleField.id).all()
        records = (
            ModuleRecord.query.filter_by(module_id=mid, group_id=None)
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
        "worker/module_manage.html", module=m, fields=fields, records=records,
        active_group=active_group
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


@worker_bp.route("/modules/<int:mid>/delete", methods=["POST"])
@worker_required
@active_subscription_required
def delete_module(mid):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403
    
    try:
        # 1. Disconnect Campaigns from this module, its groups, and its scripts
        campaigns = Campaign.query.filter_by(module_id=mid).all()
        for c in campaigns:
            c.module_id = None
            c.group_id = None
            c.script_id = None
        db.session.flush()

        # 2. Get all record IDs for cleaning up record values
        record_ids = [r.id for r in ModuleRecord.query.filter_by(module_id=mid).all()]
        if record_ids:
            ModuleRecordValue.query.filter(ModuleRecordValue.record_id.in_(record_ids)).delete(synchronize_session=False)
            ModuleRecord.query.filter(ModuleRecord.id.in_(record_ids)).delete(synchronize_session=False)

        # 3. Delete scripts associated with the module
        Script.query.filter_by(module_id=mid).delete(synchronize_session=False)

        # 4. Delete fields and groups
        ModuleField.query.filter_by(module_id=mid).delete(synchronize_session=False)
        ModuleGroup.query.filter_by(module_id=mid).delete(synchronize_session=False)

        # 5. Delete the module itself
        db.session.delete(m)
        db.session.commit()
        
        ChangeRequest.log(
            current_user.organization_id,
            current_user.id,
            "Module Deletion",
            new_val=f"Module '{m.name}' was permanently deleted",
        )
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@worker_bp.route("/profile", methods=["GET", "POST"])
@worker_required
def profile():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        phone = request.form.get("phone")

        current_user.full_name = full_name
        current_user.phone = phone
        
        # Handle profile photo upload
        profile_photo = request.files.get("profile_photo")
        if profile_photo and profile_photo.filename:
            filename = secure_filename(f"user_{current_user.id}_{profile_photo.filename}")
            upload_path = os.path.join("app", "static", "uploads", "profiles", filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            profile_photo.save(upload_path)
            current_user.profile_photo = f"uploads/profiles/{filename}"

        db.session.commit()

        flash("Profile updated successfully", "success")
        return redirect(url_for("worker.profile"))

    return render_template("worker/profile.html", user=current_user)


@worker_bp.route("/preferences", methods=["GET", "POST"])
@worker_required
def preferences():
    if request.method == "POST":
        theme = request.form.get("theme", "light")
        language = request.form.get("language", "English")
        
        prefs = current_user.preferences or {}
        prefs["theme"] = theme
        prefs["language"] = language
        
        # In SQLAlchemy JSON columns, we sometimes need to explicitly mark it as modified
        current_user.preferences = prefs
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(current_user, "preferences")
        
        db.session.commit()
        
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
            # Session hardening for OAuth org-select login
            from app.security.session_manager import SessionManager

            SessionManager.regenerate_session()
            SessionManager.track_session(user.id, "org_user")
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
            link=url_for("super_admin.pending_changes"),
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

    group_id = request.form.get("group_id")
    if not group_id:
        flash("Group ID is required to add a record.", "danger")
        return redirect(url_for("worker.manage_module", mid=mid))

    group = ModuleGroup.query.get(group_id)

    # Create the record
    record = ModuleRecord(module_id=mid, group_id=group_id, created_by_id=current_user.id)
    db.session.add(record)
    db.session.flush()  # Get the record ID

    # Add values
    fields = ModuleField.query.filter_by(module_id=mid, group_id=group_id).all()
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
                    .filter(ModuleRecord.group_id == group_id)
                    .first()
                )
                if existing:
                    db.session.rollback()
                    flash(
                        f"Duplicate detected inside group '{group.name if group else 'unknown'}'. Number: {val_text}",
                        "danger",
                    )
                    return redirect(url_for("worker.manage_module", mid=mid, group=group_id))

            val = ModuleRecordValue(record_id=record.id, field_id=f.id, value=val_text)
            db.session.add(val)

    db.session.commit()
    ChangeRequest.log(current_user.organization_id, current_user.id, f"Added Record to Module: {m.name}")
    flash("Record added successfully", "success")
    return redirect(url_for("worker.manage_module", mid=mid, group=group_id))


@worker_bp.route("/api/records/<int:rid>")
@worker_required
def get_record_api(rid):
    r = db.get_or_404(ModuleRecord, rid)
    m = db.session.get(Module, r.module_id)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    fields = ModuleField.query.filter_by(module_id=m.id, group_id=r.group_id).all()
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


@worker_bp.route("/api/records/<int:rid>/update", methods=["POST"])
@worker_required
def update_record_api(rid):
    r = db.get_or_404(ModuleRecord, rid)
    m = db.session.get(Module, r.module_id)
    if m.organization_id != current_user.organization_id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    # Update values
    fields = ModuleField.query.filter_by(module_id=m.id, group_id=r.group_id).all()
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
                .filter(ModuleRecord.module_id == m.id, ModuleRecord.group_id == r.group_id)
                .first()
            )
            if existing:
                flash(
                    f"Update failed: '{val_text}' is already registered for '{f.name}'.",
                    "danger",
                )
                return redirect(url_for("worker.manage_module", mid=m.id, group=r.group_id))

        if val_obj:
            val_obj.value = val_text
        else:
            val_obj = ModuleRecordValue(record_id=rid, field_id=f.id, value=val_text)
            db.session.add(val_obj)

    db.session.commit()
    flash("Record updated successfully", "success")
    return redirect(url_for("worker.manage_module", mid=m.id, group=r.group_id))


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

        group_id = request.args.get("group_id", type=int) or data.get("group_id")

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

    group_id = request.args.get("group_id", type=int)
    fields_query = ModuleField.query.filter_by(module_id=mid)
    if group_id:
        fields_query = fields_query.filter_by(group_id=group_id)
    else:
        fields_query = fields_query.filter_by(group_id=None)
        
    fields = fields_query.all()
    return jsonify(
        {
            "success": True,
            "fields": [
                {"id": f.id, "name": f.name, "type": f.field_type, "is_unique": f.is_unique, "meta": f.meta}
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
        group_id = request.args.get("group_id", type=int)
        fields_query = ModuleField.query.filter_by(module_id=mid)
        if group_id:
            fields_query = fields_query.filter_by(group_id=group_id)
        else:
            fields_query = fields_query.filter_by(group_id=None)
            
        fields = fields_query.all()
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

            record = ModuleRecord(module_id=mid, group_id=group_id, created_by_id=current_user.id)
            db.session.add(record)
            db.session.flush()

            for col in df.columns:
                f_obj = field_map.get(col.lower())
                if f_obj and f_obj.field_type not in ["calculated", "boolean"]:
                    val = str(row[col]) if pd.notnull(row[col]) else ""
                    db.session.add(
                        ModuleRecordValue(
                            record_id=record.id, field_id=f_obj.id, value=val
                        )
                    )
            import_count += 1

        db.session.commit()
        ChangeRequest.log(current_user.organization_id, current_user.id, f"Imported {import_count} Records to Module: {m.name}")
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

    if request.args.get("group_id"):
        return redirect(url_for("worker.manage_module", mid=mid, group=request.args.get("group_id")))
    return redirect(url_for("worker.manage_module", mid=mid))


@worker_bp.route("/modules/<int:mid>/export/<string:format>")
@worker_required
def export_records(mid, format):
    m = db.get_or_404(Module, mid)
    if m.organization_id != current_user.organization_id:
        flash("Access denied", "danger")
        return redirect(url_for("worker.dashboard"))

    group_id = request.args.get("group_id", type=int)
    
    fields_query = ModuleField.query.filter_by(module_id=mid)
    records_query = ModuleRecord.query.filter_by(module_id=mid)
    
    if group_id:
        fields_query = fields_query.filter_by(group_id=group_id)
        records_query = records_query.filter_by(group_id=group_id)
    else:
        fields_query = fields_query.filter_by(group_id=None)
        records_query = records_query.filter_by(group_id=None)
        
    fields = fields_query.all()
    records = records_query.all()

    data = []
    for r in records:
        row = {"Date Created": r.created_at.strftime("%Y-%m-%d %H:%M")}
        vals = r.field_values
        for f in fields:
            if f.field_type in ["calculated", "boolean"]:
                row[f.name] = evaluate_logic(r, f)
            else:
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


# ============================================================
# MODULE GROUPS
# ============================================================

@worker_bp.route("/modules/<int:mid>/groups")
@worker_required
@active_subscription_required
def manage_groups(mid):
    module = Module.query.filter_by(
        id=mid, organization_id=current_user.organization_id
    ).first_or_404()
    return render_template("worker/groups.html", module=module)


@worker_bp.route("/modules/<int:mid>/groups/add", methods=["POST"])
@worker_required
@active_subscription_required
def add_group(mid):
    module = Module.query.filter_by(
        id=mid, organization_id=current_user.organization_id
    ).first_or_404()
    name = request.form.get("name", "").strip()
    if not name:
        flash("Group name is required.", "danger")
        return redirect(url_for("worker.manage_groups", mid=mid, **request.args))
    group = ModuleGroup(module_id=mid, name=name)
    db.session.add(group)
    db.session.commit()
    ChangeRequest.log(current_user.organization_id, current_user.id, f"Created Group: {name}")
    flash(f'Group "{name}" created successfully.', "success")
    return redirect(url_for("worker.manage_module", mid=mid, group=group.id, **request.args))


@worker_bp.route("/groups/<int:gid>/edit", methods=["POST"])
@worker_required
@active_subscription_required
def edit_group(gid):
    group = ModuleGroup.query.get_or_404(gid)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    name = request.form.get("name", "").strip()
    if not name:
        flash("Group name is required.", "danger")
        return redirect(url_for("worker.manage_groups", mid=module.id))
    group.name = name
    db.session.commit()
    flash("Group updated.", "success")
    return redirect(url_for("worker.manage_groups", mid=module.id))


@worker_bp.route("/groups/<int:gid>/delete", methods=["POST"])
@worker_required
@active_subscription_required
def delete_group(gid):
    group = ModuleGroup.query.get_or_404(gid)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    mid = module.id
    db.session.delete(group)
    db.session.commit()
    flash("Group deleted.", "success")
    return redirect(url_for("worker.manage_groups", mid=mid))


@worker_bp.route("/groups/<int:gid>/dashboard")
@worker_required
@active_subscription_required
def group_dashboard(gid):
    group = ModuleGroup.query.get_or_404(gid)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    scripts = Script.query.filter_by(group_id=gid).all()
    campaigns = Campaign.query.filter_by(
        group_id=gid, organization_id=current_user.organization_id
    ).order_by(Campaign.created_at.desc()).all()
    return render_template(
        "worker/groups.html",
        module=module,
        group=group,
        scripts=scripts,
        campaigns=campaigns,
    )


# ============================================================
# SCRIPTS
# ============================================================


@worker_bp.route("/api/groups/<int:gid>/script-variables")
@worker_required
def group_script_variables_api(gid):
    """Returns dynamic variables from the group's active schema fields.
    
    Variables are group-scoped: Group 18 variables ≠ Group 19 variables.
    """
    group = ModuleGroup.query.get_or_404(gid)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    
    # Load ONLY fields belonging to this group
    fields = ModuleField.query.filter_by(group_id=gid).all()
    
    # Icon mapping by field_type
    ICON_MAP = {
        "phone": "bi-telephone",
        "email": "bi-envelope",
        "text": "bi-type",
        "string": "bi-type",
        "language": "bi-globe",
        "number": "bi-hash",
        "integer": "bi-hash",
        "date": "bi-calendar",
        "datetime": "bi-calendar-event",
        "boolean": "bi-toggle-on",
        "dropdown": "bi-list",
        "multiple_choice": "bi-ui-checks",
        "textarea": "bi-text-paragraph",
        "url": "bi-link-45deg",
        "file": "bi-paperclip",
    }
    
    variables = []
    
    print(f"\n[GROUP]\n{gid}\n")
    if not fields:
        print("[NO SCHEMA FOR GROUP]\n")
    else:
        print(f"[SCHEMA FOUND]\n{len(fields)}\n")
        print("[VARIABLES RETURNED]\n")
        for f in fields:
            print(f.name.strip())
            ft = (f.field_type or "text").lower()
            variables.append({
                "key": f.name.strip(),
                "label": f.name.strip(),
                "placeholder": "{{" + f.name.strip() + "}}",
                "type": ft,
                "icon": ICON_MAP.get(ft, "bi-tag"),
                "field_id": f.id,
            })
        print()
    
    return jsonify({"variables": variables, "group_id": gid, "group_name": group.name})


@worker_bp.route("/groups/<int:gid>/scripts", methods=["GET", "POST"])
@worker_required
@active_subscription_required
def scripts(gid):
    group = ModuleGroup.query.get_or_404(gid)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    # Group-scoped fields: load ONLY fields belonging to this group
    fields = ModuleField.query.filter_by(group_id=gid).all()

    if request.method == "POST":
        comm_type = request.form.get("type", "whatsapp_text")
        language = request.form.get("language", "English")
        content = request.form.get("content", "").strip()
        backup_enabled = request.form.get("backup_enabled") == "on"
        backup_template = request.form.get("backup_template", "").strip()
        
        if not content:
            flash("Script content is required.", "danger")
            return redirect(url_for("worker.scripts", gid=gid))

        import re
        valid_field_names = [f.name.strip() for f in fields]
        
        used_vars = re.findall(r'\{\{(.*?)\}\}', content)
        invalid_vars = [v.strip() for v in used_vars if v.strip() not in valid_field_names]
        if invalid_vars:
            flash(f"Invalid variables used in content: {', '.join(invalid_vars)}", "danger")
            return redirect(url_for("worker.scripts", gid=gid))
            
        if backup_enabled and backup_template:
            used_backup_vars = re.findall(r'\{\{(.*?)\}\}', backup_template)
            invalid_backup_vars = [v.strip() for v in used_backup_vars if v.strip() not in valid_field_names]
            if invalid_backup_vars:
                flash(f"Invalid variables used in backup template: {', '.join(invalid_backup_vars)}", "danger")
                return redirect(url_for("worker.scripts", gid=gid))

        script = Script(
            module_id=module.id,
            group_id=gid,
            language=language,
            type=comm_type,
            content=content,
            backup_enabled=backup_enabled,
            backup_template=backup_template
        )
        db.session.add(script)
        db.session.commit()
        flash("Script created successfully.", "success")
        return redirect(url_for("worker.scripts", gid=gid))

    all_scripts = Script.query.filter_by(group_id=gid).order_by(Script.id.desc()).all()
    return render_template(
        "worker/scripts.html",
        module=module,
        group=group,
        scripts=all_scripts,
        fields=fields,
    )


@worker_bp.route("/scripts/<int:sid>/edit", methods=["GET", "POST"])
@worker_required
@active_subscription_required
def edit_script(sid):
    script = Script.query.get_or_404(sid)
    group = ModuleGroup.query.get_or_404(script.group_id)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    # Group-scoped fields: load ONLY fields belonging to this group
    fields = ModuleField.query.filter_by(group_id=script.group_id).all()

    if request.method == "POST":
        script.type = request.form.get("type", script.type)
        script.language = request.form.get("language", script.language)
        content = request.form.get("content", "").strip()
        script.backup_enabled = request.form.get("backup_enabled") == "on"
        script.backup_template = request.form.get("backup_template", "").strip()

        if not content:
            flash("Content cannot be empty.", "danger")
            return redirect(url_for("worker.edit_script", sid=sid))

        import re
        valid_field_names = [f.name.strip() for f in fields]
        
        used_vars = re.findall(r'\{\{(.*?)\}\}', content)
        invalid_vars = [v.strip() for v in used_vars if v.strip() not in valid_field_names]
        if invalid_vars:
            flash(f"Invalid variables used in content: {', '.join(invalid_vars)}", "danger")
            return redirect(url_for("worker.edit_script", sid=sid))
            
        if script.backup_enabled and script.backup_template:
            used_backup_vars = re.findall(r'\{\{(.*?)\}\}', script.backup_template)
            invalid_backup_vars = [v.strip() for v in used_backup_vars if v.strip() not in valid_field_names]
            if invalid_backup_vars:
                flash(f"Invalid variables used in backup template: {', '.join(invalid_backup_vars)}", "danger")
                return redirect(url_for("worker.edit_script", sid=sid))

        script.content = content
        db.session.commit()
        flash("Script updated.", "success")
        return redirect(url_for("worker.scripts", gid=group.id))

    return render_template(
        "worker/script_edit.html",
        script=script,
        group=group,
        module=module,
        fields=fields,
    )


@worker_bp.route("/scripts/<int:sid>/delete", methods=["POST"])
@worker_required
@active_subscription_required
def delete_script(sid):
    script = Script.query.get_or_404(sid)
    group = ModuleGroup.query.get_or_404(script.group_id)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()
    gid = group.id
    db.session.delete(script)
    db.session.commit()
    flash("Script deleted.", "success")
    return redirect(url_for("worker.scripts", gid=gid))


@worker_bp.route("/preview-voice", methods=["POST"])
@worker_required
def preview_voice():
    """Generate a TTS audio preview and return the static URL."""
    try:
        data = request.get_json(force=True)
        text = (data.get("text") or "").strip()
        language = (data.get("language") or "English").strip()

        if not text:
            return jsonify({"success": False, "error": "No text provided."})

        # Map language name to 2-letter code
        lang_map = {
            "English": "en",
            "Hindi": "hi",
            "Kannada": "kn",
            "Tamil": "ta",
            "Telugu": "te",
            "Malayalam": "ml",
            "Marathi": "mr",
            "Punjabi": "pa",
            "Gujarati": "gu",
        }
        lang_code = lang_map.get(language, "en")

        # Create output directory
        audio_dir = os.path.join(current_app.root_path, "static", "audio", "previews")
        audio_dir = os.path.abspath(audio_dir)
        os.makedirs(audio_dir, exist_ok=True)

        filename = f"preview_{uuid.uuid4().hex}.mp3"
        output_path = os.path.join(audio_dir, filename)

        # Run async TTS generation synchronously
        from app.common.audio.generator import get_voice_generator
        generator = get_voice_generator()
        asyncio.run(generator.generate_audio(text, lang_code, output_path))

        audio_url = f"/static/audio/previews/{filename}"
        return jsonify({"success": True, "audio_url": audio_url})

    except Exception as e:
        current_app.logger.error(f"[preview_voice] error: {e}")
        return jsonify({"success": False, "error": str(e)})


# ============================================================
# CAMPAIGNS
# ============================================================

@worker_bp.route("/groups/<int:gid>/campaigns", methods=["GET", "POST"])
@worker_required
@active_subscription_required
def campaigns(gid):
    group = ModuleGroup.query.get_or_404(gid)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        comm_type = request.form.get("type", "whatsapp_text")
        script_id = request.form.get("script_id") or None
        sender_number_id = request.form.get("sender_number_id") or None

        if not name:
            flash("Campaign name is required.", "danger")
            return redirect(url_for("worker.campaigns", gid=gid))
            
        # Check active campaigns limits
        from app.models import Subscription
        sub = Subscription.query.filter_by(
            organization_id=current_user.organization_id
        ).first()
        
        from app.core.constants import PLAN_LIMITS
        plan_name = (sub.plan or "Free Trial").lower() if sub else "free trial"
        plan_limits = PLAN_LIMITS.get(plan_name, PLAN_LIMITS["free trial"])
        
        current_campaigns_count = Campaign.query.filter_by(
            organization_id=current_user.organization_id
        ).count()
        
        if current_campaigns_count >= plan_limits["campaigns"]:
            flash(
                f"Your organization has reached the plan limit of {plan_limits['campaigns']} campaigns. Please upgrade your subscription plan to create more.",
                "danger"
            )
            return redirect(url_for("worker.campaigns", gid=gid))
            
        if script_id:
            script = Script.query.get(script_id)
            if script and script.type != comm_type:
                flash("Selected script is not compatible with the chosen campaign type.", "danger")
                return redirect(url_for("worker.campaigns", gid=gid))

        campaign = Campaign(
            organization_id=current_user.organization_id,
            module_id=module.id,
            group_id=gid,
            name=name,
            type=comm_type,
            script_id=int(script_id) if script_id else None,
            sender_number_id=int(sender_number_id) if sender_number_id else None,
            status="draft",
            created_by_id=current_user.id,
        )
        db.session.add(campaign)
        db.session.commit()
        ChangeRequest.log(current_user.organization_id, current_user.id, f"Created Campaign: {name}")
        db.session.commit()
        flash(f'Campaign "{name}" created as draft.', "success")
        return redirect(url_for("worker.campaigns", gid=gid))

    all_campaigns = Campaign.query.filter_by(
        group_id=gid, organization_id=current_user.organization_id
    ).order_by(Campaign.created_at.desc()).all()

    scripts_list = Script.query.filter_by(group_id=gid).all()
    numbers = CommunicationNumber.query.filter_by(
        organization_id=current_user.organization_id
    ).all()

    return render_template(
        "worker/campaigns.html",
        module=module,
        group=group,
        campaigns=all_campaigns,
        scripts=scripts_list,
        numbers=numbers,
    )


@worker_bp.route("/campaigns/<int:cid>/start", methods=["POST"])
@worker_required
@active_subscription_required
def start_campaign(cid):
    print(f"\n[ROUTE] start_campaign hit for cid {cid}", file=sys.stderr, flush=True)
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()

    if campaign.status != "draft":
        flash("Only draft campaigns can be started.", "warning")
        return redirect(url_for("worker.campaigns", gid=campaign.group_id))

    # Gather target records from the group
    group = ModuleGroup.query.get_or_404(campaign.group_id)
    records = group.records  # relies on backref from ModuleRecord -> ModuleGroup

    if not records:
        flash("No records in this group to target.", "warning")
        return redirect(url_for("worker.campaigns", gid=campaign.group_id))

    campaign.status = "running"
    db.session.commit()
    
    from app.services.campaign_runner import CampaignExecutionService
    CampaignExecutionService.start(cid)
    
    flash(
        f'Campaign "{campaign.name}" is now running with {len(records)} target(s).',
        "success",
    )
    return redirect(url_for("worker.campaign_report", cid=cid))


@worker_bp.route("/campaigns/<int:cid>/restart", methods=["POST"])
@worker_required
@active_subscription_required
def restart_campaign(cid):
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()

    if campaign.status not in ["completed", "failed", "paused"]:
        flash("Only completed, failed, or paused campaigns can be run again.", "warning")
        return redirect(url_for("worker.campaigns", gid=campaign.group_id))

    # Reset all targets for this campaign
    targets = CampaignTarget.query.filter_by(campaign_id=cid).all()
    for target in targets:
        target.status = "queued"
        target.call_attempts = 0
        target.retry_count = 0
        target.completed_at = None
        target.end_reason = None
        target.last_attempt_at = None
        target.next_retry_at = None

    campaign.status = "running"
    db.session.commit()

    from app.services.campaign_runner import CampaignExecutionService
    CampaignExecutionService.start(cid)

    flash(
        f'Campaign "{campaign.name}" has been restarted and is now running again.',
        "success",
    )
    return redirect(url_for("worker.campaign_report", cid=cid))


@worker_bp.route("/campaigns/<int:cid>/edit", methods=["GET", "POST"])
@worker_required
@active_subscription_required
def edit_campaign(cid):
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()
    
    group = ModuleGroup.query.get_or_404(campaign.group_id)
    module = Module.query.filter_by(
        id=group.module_id, organization_id=current_user.organization_id
    ).first_or_404()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        comm_type = request.form.get("type", "whatsapp_text")
        script_id = request.form.get("script_id") or None
        sender_number_id = request.form.get("sender_number_id") or None

        if not name:
            flash("Campaign name is required.", "danger")
            return redirect(url_for("worker.edit_campaign", cid=cid))

        if script_id:
            script = Script.query.get(script_id)
            if script and script.type != comm_type:
                flash("Selected script is not compatible with the chosen campaign type.", "danger")
                return redirect(url_for("worker.edit_campaign", cid=cid))

        campaign.name = name
        campaign.type = comm_type
        campaign.script_id = int(script_id) if script_id else None
        campaign.sender_number_id = int(sender_number_id) if sender_number_id else None
        
        db.session.commit()
        ChangeRequest.log(current_user.organization_id, current_user.id, f"Edited Campaign: {name}")
        db.session.commit()
        flash(f'Campaign "{name}" updated successfully.', "success")
        return redirect(url_for("worker.campaigns", gid=campaign.group_id))

    scripts_list = Script.query.filter_by(group_id=campaign.group_id).all()
    numbers = CommunicationNumber.query.filter_by(
        organization_id=current_user.organization_id
    ).all()

    return render_template(
        "worker/campaign_edit.html",
        campaign=campaign,
        module=module,
        group=group,
        scripts=scripts_list,
        numbers=numbers,
    )


@worker_bp.route("/campaigns/<int:cid>/report")
@worker_required
@active_subscription_required
def campaign_report(cid):
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()
    group  = ModuleGroup.query.get(campaign.group_id)
    module = Module.query.filter_by(
        id=campaign.module_id, organization_id=current_user.organization_id
    ).first_or_404()

    targets = (CampaignTarget.query
               .filter_by(campaign_id=cid)
               .order_by(CampaignTarget.id.asc())
               .all())

    # Build rich row data joining record for phone/name
    rows = []
    for t in targets:
        record = ModuleRecord.query.get(t.record_id) if t.record_id else None
        nv     = record.named_values if record else {}
        phone  = None
        name   = None
        if record:
            from app.services.campaign_runner import _extract_phone_from_record
            phone = _extract_phone_from_record(record)
            name  = nv.get("name") or nv.get("Name") or ""
        rows.append({
            "target": t,
            "phone":  phone or "—",
            "name":   name  or "—",
        })

    total          = len(targets)
    answered_count = sum(1 for t in targets if t.status in ("answered", "completed"))
    retry_count    = sum(1 for t in targets if t.status in ("retry_pending", "retrying"))
    wa_count       = sum(1 for t in targets if t.status == "whatsapp_sent")
    failed_count   = sum(1 for t in targets if t.status == "failed")
    waiting_count  = sum(1 for t in targets if t.status == "waiting_webhook")
    queued_count   = sum(1 for t in targets if t.status in ("queued", "calling"))

    stats = {
        "total":    total,
        "answered": answered_count,
        "retrying": retry_count,
        "whatsapp": wa_count,
        "failed":   failed_count,
        "waiting":  waiting_count,
        "queued":   queued_count,
    }

    return render_template(
        "worker/campaign_report.html",
        campaign=campaign,
        group=group,
        module=module,
        rows=rows,
        stats=stats,
    )


@worker_bp.route("/campaigns/<int:cid>/report-data")
@worker_required
def campaign_report_data(cid):
    """Live JSON endpoint polled every 15 s by the report page."""
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()

    targets = CampaignTarget.query.filter_by(campaign_id=cid).all()

    STATUS_COLOR = {
        "answered":      "success",
        "completed":     "success",
        "retry_pending": "warning",
        "retrying":      "orange",
        "whatsapp_sent": "info",
        "waiting_webhook": "gray",
        "calling":       "gray",
        "queued":        "gray",
        "failed":        "danger",
    }

    rows = []
    for t in targets:
        record = ModuleRecord.query.get(t.record_id) if t.record_id else None
        nv     = record.named_values if record else {}
        from app.services.campaign_runner import _extract_phone_from_record
        phone = _extract_phone_from_record(record) if record else None
        rows.append({
            "id":             t.id,
            "phone":          phone or "—",
            "name":           nv.get("name") or nv.get("Name") or "—",
            "status":         t.status,
            "color":          STATUS_COLOR.get(t.status, "gray"),
            "call_attempts":  t.call_attempts,
            "retry_count":    t.retry_count or 0,
            "connected":      t.connected,
            "duration":       t.duration or 0,
            "whatsapp_sent":  t.whatsapp_sent,
            "next_retry_at":  t.next_retry_at.isoformat() if t.next_retry_at else None,
            "last_webhook_at":t.last_webhook_at.isoformat() if t.last_webhook_at else None,
            "completed_at":   t.completed_at.isoformat() if t.completed_at else None,
            "end_reason":     t.end_reason or "",
        })

    total = len(targets)
    stats = {
        "total":    total,
        "answered": sum(1 for t in targets if t.status in ("answered","completed")),
        "retrying": sum(1 for t in targets if t.status in ("retry_pending","retrying")),
        "whatsapp": sum(1 for t in targets if t.status == "whatsapp_sent"),
        "failed":   sum(1 for t in targets if t.status == "failed"),
        "waiting":  sum(1 for t in targets if t.status == "waiting_webhook"),
        "queued":   sum(1 for t in targets if t.status in ("queued","calling")),
    }
    return jsonify({"rows": rows, "stats": stats, "campaign_status": campaign.status})



@worker_bp.route("/campaigns/<int:cid>/download-report")
@worker_required
@active_subscription_required
def download_report(cid):
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()
    logs = DeliveryLog.query.filter_by(campaign_id=cid).order_by(
        DeliveryLog.created_at.desc()
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Recipient", "Channel", "Status", "SID", "Error", "Created At"])
    for log in logs:
        writer.writerow([
            log.recipient,
            log.channel,
            log.status,
            log.sid,
            log.error or "",
            log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
        ])

    from flask import make_response
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = (
        f'attachment; filename="campaign_{cid}_report.csv"'
    )
    response.headers["Content-Type"] = "text/csv"
    return response


@worker_bp.route("/campaigns/<int:cid>/delete", methods=["POST"])
@worker_required
@active_subscription_required
def delete_campaign(cid):
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()
    gid = campaign.group_id
    db.session.delete(campaign)
    db.session.commit()
    flash("Campaign deleted.", "success")
    return redirect(url_for("worker.campaigns", gid=gid))


@worker_bp.route("/campaigns/bulk-delete", methods=["POST"])
@worker_required
@active_subscription_required
def bulk_delete_campaigns():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400
    
    campaign_ids = data.get("campaign_ids", [])
    if not campaign_ids:
        return jsonify({"success": False, "message": "No campaigns selected"}), 400

    campaigns = Campaign.query.filter(
        Campaign.id.in_(campaign_ids),
        Campaign.organization_id == current_user.organization_id
    ).all()

    if not campaigns:
        return jsonify({"success": False, "message": "No valid campaigns found"}), 404

    try:
        for c in campaigns:
            if c.status == "running":
                return jsonify({"success": False, "message": "Stop campaign before deleting"}), 400
            db.session.delete(c)
        
        db.session.commit()
        print(f"[BULK-DELETE] Successfully deleted {len(campaigns)} campaigns.", file=sys.stderr, flush=True)
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@worker_bp.route("/api/campaigns/bulk-action", methods=["POST"])
@worker_required
@active_subscription_required
def bulk_action_campaigns():
    data = request.json
    print(f"\n[ROUTE] bulk_action_campaigns hit with data: {data}", file=sys.stderr, flush=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    action = data.get("action")
    campaign_ids = data.get("ids", [])
    if not action or not campaign_ids:
        return jsonify({"error": "Missing action or ids"}), 400
        
    campaigns = Campaign.query.filter(
        Campaign.id.in_(campaign_ids),
        Campaign.organization_id == current_user.organization_id
    ).all()
    
    if not campaigns:
        return jsonify({"error": "No valid campaigns found"}), 404
        
    try:
        if action == "assign":
            script_id = data.get("extra_data", {}).get("script_id")
            if not script_id:
                return jsonify({"error": "Missing script ID"}), 400
            for c in campaigns:
                c.script_id = script_id
            db.session.commit()
            return jsonify({"success": True, "message": f"Assigned script to {len(campaigns)} campaigns."})
            
        elif action == "move":
            group_id = data.get("extra_data", {}).get("group_id")
            if not group_id:
                return jsonify({"error": "Missing group ID"}), 400
            for c in campaigns:
                c.group_id = group_id
            db.session.commit()
            return jsonify({"success": True, "message": f"Moved {len(campaigns)} campaigns."})
            
        elif action in ["start", "pause", "restart", "stop"]:
            new_status = {
                "start": "running",
                "pause": "paused",
                "restart": "running",
                "stop": "completed"
            }.get(action)
            
            from app.services.campaign_runner import CampaignExecutionService
            to_start = []
            for c in campaigns:
                # Validation for start/restart
                if action in ["start", "restart"]:
                    if not c.script_id:
                        return jsonify({"error": f"Campaign '{c.name}' missing script."}), 400
                    if not c.group_id:
                        return jsonify({"error": f"Campaign '{c.name}' missing group."}), 400
                        
                c.status = new_status
                if action in ["start", "restart"]:
                    to_start.append(c.id)
                    
            db.session.commit()
            
            print(f"[BULK-ACTION] Starting/restarting {len(to_start)} campaigns.", file=sys.stderr, flush=True)
            for cid in to_start:
                CampaignExecutionService.start(cid)
                
            print(f"[BULK-ACTION] {new_status} applied to {len(campaigns)} campaigns successfully.", file=sys.stderr, flush=True)
            return jsonify({"success": True, "message": f"Marked {len(campaigns)} campaigns as {new_status}."})
            
        elif action == "duplicate":
            for c in campaigns:
                new_c = Campaign(
                    organization_id=c.organization_id,
                    module_id=c.module_id,
                    group_id=c.group_id,
                    name=f"{c.name} (Copy)",
                    type=c.type,
                    script_id=c.script_id,
                    status="draft"
                )
                db.session.add(new_c)
            db.session.commit()
            return jsonify({"success": True, "message": f"Duplicated {len(campaigns)} campaigns."})
            
        return jsonify({"error": f"Unknown action: {action}"}), 400
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@worker_bp.route("/api/humanlab/webhook", methods=["POST"])
@csrf.exempt
def humanlab_webhook():
    """Receive webhook from Hooman Labs. Passes full payload for rich status extraction."""
    import sys
    data = request.json
    print(f"\n[WEBHOOK ROUTE] Incoming webhook payload: {data}", file=sys.stderr, flush=True)
    
    if not data:
        return jsonify({"success": False, "error": "No JSON payload"}), 400
    
    # Accept any valid webhook — the handler will figure out the target
    from flask import current_app
    app = current_app._get_current_object()
    result = CampaignExecutionService.handle_webhook(app, data)
    
    return jsonify({"success": bool(result)})


@worker_bp.route("/api/campaign/<int:cid>/status")
@worker_required
def campaign_status_api(cid):
    """Polling endpoint for real-time campaign status updates."""
    campaign = Campaign.query.filter_by(
        id=cid, organization_id=current_user.organization_id
    ).first_or_404()
    
    targets = CampaignTarget.query.filter_by(campaign_id=cid).all()
    logs = DeliveryLog.query.filter_by(campaign_id=cid).order_by(
        DeliveryLog.created_at.desc()
    ).all()
    
    # Build target summaries
    target_data = []
    for t in targets:
        target_data.append({
            "id": t.id,
            "status": t.status,
            "call_status": t.call_status or t.last_call_status,
            "connected": t.connected,
            "duration": t.duration,
            "end_reason": t.end_reason,
            "attempts": t.call_attempts,
            "conversation_id": t.conversation_id,
            "last_webhook_at": t.last_webhook_at.isoformat() if t.last_webhook_at else None,
        })
    
    # Count statuses
    from collections import Counter
    status_counts = dict(Counter([t.status for t in targets]))
    log_status_counts = dict(Counter([l.status for l in logs]))
    
    return jsonify({
        "campaign_id": cid,
        "campaign_status": campaign.status,
        "total_targets": len(targets),
        "target_statuses": status_counts,
        "log_statuses": log_status_counts,
        "targets": target_data,
        "is_terminal": campaign.status in ("completed", "failed"),
    })


@worker_bp.route("/api/humanlab/debug")
@worker_required
def humanlab_debug():
    """Debug endpoint — shows resolved Hooman config for current org (API key masked)."""
    from app.services.humanlab_provider import get_hooman_config
    org_id = current_user.organization_id
    cfg = get_hooman_config(org_id)
    
    api_key = cfg["api_key"]
    masked = (api_key[:6] + "****" + api_key[-4:]) if len(api_key) > 10 else ("****" if api_key else "EMPTY")
    
    return jsonify({
        "organization_id": org_id,
        "source": "database (org.hooman_config)",
        "api_key": masked,
        "api_key_length": len(api_key),
        "api_key_present": bool(api_key),
        "campaign": cfg["campaign"],
        "from_number": cfg["from_number"],
        "from_number_present": bool(cfg["from_number"]),
        "hooman_org_id": cfg["organization_id"],
        "base_url": current_app.config.get("BASE_URL", ""),
        "note": "api_key & from_number come ONLY from org DB config, set by platform admin."
    })
