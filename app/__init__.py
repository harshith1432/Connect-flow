import os
import platform
import sys
import time
import logging
import mimetypes

# Ensure .mp3 files are served with the correct Content-Type.
mimetypes.add_type("audio/mpeg", ".mp3")

# Monkey-patch platform to prevent WMI hang on Windows
if os.name == "nt":
    import collections

    uname_result = collections.namedtuple(
        "uname_result", "system node release version machine processor"
    )
    platform.uname = lambda: uname_result(
        "Windows", "mock_node", "10", "10.0.19041", "AMD64", "AMD64"
    )
    platform.system = lambda: "Windows"
    platform.machine = lambda: "AMD64"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    platform.win32_ver = lambda *args, **kwargs: (
        "10",
        "10.0.19041",
        "",
        "Multiprocessor Free",
    )

from flask import Flask, request, g, jsonify
from flask_migrate import Migrate
from sqlalchemy import text
from datetime import datetime

from app.config import Config
from app.extensions import db, migrate, login_manager, csrf


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Configure Upload Folder
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "instance", "uploads")
    if not os.path.exists(app.config["UPLOAD_FOLDER"]):
        os.makedirs(app.config["UPLOAD_FOLDER"])

    # Configure root logger — only show WARNING+ to keep terminal clean
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    # Force UTF-8 on Windows — prevents UnicodeEncodeError for non-ASCII
    # chars (e.g. arrows, em-dashes) when the console uses cp1252.
    try:
        if hasattr(stderr_handler.stream, 'reconfigure'):
            stderr_handler.stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(stderr_handler)
    root.setLevel(logging.WARNING)  # Only warnings/errors from libraries

    # Werkzeug — show startup info only
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.WARNING)
    werkzeug_logger.propagate = False

    # Quiet noisy loggers
    for name in ("sqlalchemy.engine", "urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.WARNING)


    # Initialize robust request logging FIRST (must be before security hooks)
    from app.core.logging_system import setup_full_debug_logging
    setup_full_debug_logging(app)

    @app.before_request
    def enforce_security():
        # Exclude static requests from before_request hooks
        if request.path.startswith("/static/") or request.path.startswith("/static"):
            return

        from flask import redirect, url_for
        from flask_login import current_user
        from app.security.session_manager import SessionManager
        from app.security.suspicious_activity import SuspiciousActivityMonitor

        # 1. Enforce session timeouts
        timeout_redirect = SessionManager.enforce_session_timeout()
        if timeout_redirect:
            return timeout_redirect

        # 2. Check for suspicious activity
        if current_user.is_authenticated:
            user_type = (
                "platform_admin"
                if hasattr(current_user, "role")
                and current_user.role == "platform_owner"
                else "org_user"
            )
            if not SuspiciousActivityMonitor.monitor_current_request(
                current_user.id, user_type
            ):
                return redirect(url_for("main.index"))

    @app.after_request
    def secure_request(response):
        # Add Cache-Control headers to prevent browser back-button caching
        if not request.path.startswith("/static"):
            response.headers[
                "Cache-Control"
            ] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response

    # Initialize DB, Migrate and Login
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.index"

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, url_for, request, flash
        
        path = request.path
        if path.startswith("/platform"):
            login_endpoint = "super_admin.login"
        elif path.startswith("/org"):
            login_endpoint = "org.login"
        elif path.startswith("/worker"):
            login_endpoint = "worker.login"
        elif path.startswith("/campaign-express"):
            login_endpoint = "campaign_express.login"
        else:
            login_endpoint = "main.index"
            
        flash("Please log in to access this page.", "warning")
        
        next_url = request.url
        return redirect(url_for(login_endpoint, next=next_url))

    # Initialize rate limiting and security headers
    from app.security.rate_limit import init_rate_limiting
    from app.security.security_headers import init_security_headers
    from app.core.session_scoping import setup_session_scoping

    init_rate_limiting(app)
    init_security_headers(app)
    setup_session_scoping(app)

    from flask_wtf.csrf import CSRFError
    from flask import redirect, request, flash
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash("Your session expired or form token was invalid. Please try submitting again.", "warning")
        return redirect(request.url)

    # loader: try platform admin, then organization users, then CE users
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import PlatformAdmin, OrganizationUser, CampaignExpressUser

        if not user_id:
            return None

        # Handle prefixed IDs to avoid collisions between tables
        if isinstance(user_id, str) and ":" in user_id:
            parts = user_id.split(":", 1)
            prefix = parts[0]
            try:
                real_id = int(parts[1])
            except ValueError:
                return None

            if prefix == "platform_admin":
                return db.session.get(PlatformAdmin, real_id)
            elif prefix == "organization_user":
                return db.session.get(OrganizationUser, real_id)
            elif prefix == "campaign_express_user":
                return db.session.get(CampaignExpressUser, real_id)

        # Fallback for old/unprefixed numeric session IDs
        try:
            numeric_id = int(user_id)
        except (ValueError, TypeError):
            return None

        u = db.session.get(PlatformAdmin, numeric_id)
        if u:
            return u
        u = db.session.get(OrganizationUser, numeric_id)
        if u:
            return u
        return db.session.get(CampaignExpressUser, numeric_id)

    # Register blueprints
    from app.features.public import main_bp
    from app.features.super_admin import super_admin_bp
    from app.features.tenant_admin import org_bp
    from app.features.workforce import worker_bp
    from app.features.api import api_bp
    from app.features.webhooks import webhooks_bp
    from app.security.routes import security_bp
    from app.features.campaign_express import campaign_express_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(security_bp, url_prefix="/security")
    app.register_blueprint(campaign_express_bp)

    # Temporary: exempt the organization registration endpoint from CSRF while
    # debugging token issues in local dev. Remove this exemption once CSRF
    # flow is validated and working for clients.
    try:
        csrf.exempt(main_bp.view_functions["main.org_register"])
    except Exception:
        pass

    # Platform owner routes are intentionally prefixed with /platform to isolate them
    app.register_blueprint(super_admin_bp, url_prefix="/platform")

    # Exempt api blueprint from CSRF checks if needed.
    csrf.exempt(api_bp)
    app.register_blueprint(org_bp, url_prefix="/org")
    app.register_blueprint(worker_bp)

    # Webhooks and internal proxies are CSRF-exempt
    app.register_blueprint(webhooks_bp, url_prefix="/webhooks")
    csrf.exempt(webhooks_bp)

    # --------------------------------------------------------------------------
    # Background Watchdog — re-triggers calls that never got a webhook
    # --------------------------------------------------------------------------
    import threading as _threading
    from datetime import timedelta as _timedelta

    def _campaign_watchdog(flask_app):
        """
        Polls every 2 minutes.
        Targets stuck in 'waiting_webhook' for > 5 minutes are treated as
        'no-answer' and the retry/WhatsApp fallback logic is triggered.
        """
        import time as _time
        _time.sleep(30)   # brief startup delay
        while True:
            try:
                with flask_app.app_context():
                    from app.models import CampaignTarget, Campaign
                    from app.services.campaign_runner import CampaignExecutionService
                    from app.core.logging_system import log_activity
                    from datetime import datetime as _dt
                    from app.extensions import db as _db

                    cutoff = _dt.utcnow() - _timedelta(minutes=5)

                    # 1) Handle stuck waiting_webhook targets
                    stuck = CampaignTarget.query.filter(
                        CampaignTarget.status == "waiting_webhook",
                        CampaignTarget.last_attempt_at <= cutoff,
                    ).all()

                    for target in stuck:
                        campaign = _db.session.get(Campaign, target.campaign_id)
                        if not campaign or campaign.status != "running":
                            continue
                        log_activity(
                            "WATCHDOG",
                            f"Target {target.id} stuck in waiting_webhook "
                            f"(attempts={target.call_attempts}) — forcing no-answer"
                        )
                        try:
                            CampaignExecutionService._handle_stuck_target(
                                flask_app, target.id
                            )
                        except Exception as _exc:
                            log_activity(
                                "WATCHDOG",
                                f"_handle_stuck_target error target {target.id}: {_exc}",
                                level="error"
                            )

                    # 2) Handle missed retry_pending timers (safety net)
                    overdue = CampaignTarget.query.filter(
                        CampaignTarget.status == "retry_pending",
                        CampaignTarget.next_retry_at != None,
                        CampaignTarget.next_retry_at <= _dt.utcnow(),
                    ).all()

                    for target in overdue:
                        campaign = _db.session.get(Campaign, target.campaign_id)
                        if not campaign or campaign.status != "running":
                            continue
                        log_activity(
                            "WATCHDOG",
                            f"Target {target.id} retry_pending overdue — firing retry"
                        )
                        try:
                            CampaignExecutionService._fire_retry(
                                flask_app, target.id
                            )
                        except Exception as _exc:
                            log_activity(
                                "WATCHDOG",
                                f"_fire_retry error target {target.id}: {_exc}",
                                level="error"
                            )

            except Exception as _ex:
                try:
                    from app.core.logging_system import log_activity
                    log_activity("WATCHDOG", f"Watchdog loop error: {_ex}", level="error")
                except Exception:
                    pass

            _time.sleep(120)   # check every 2 minutes


    _watchdog_thread = _threading.Thread(
        target=_campaign_watchdog,
        args=(app,),
        daemon=True,
        name="campaign-watchdog"
    )
    _watchdog_thread.start()

    # --------------------------------------------------------------------------
    # Hooman Webhook Proxy (Global /webhook)
    # --------------------------------------------------------------------------
    @app.route("/webhook", methods=["GET", "POST"])
    def global_webhook():
        """
        Global ingress for Hooman Labs webhooks.
        Parses call data and updates the DeliveryLog directly.
        """
        if request.method == "GET":
            return "[WEBHOOK] Endpoint is active and listening for POST requests!"

        data = request.get_json(silent=True) or {}

        # Log incoming webhook via terminal monitor
        from app.core.logging_system import log_webhook, log_activity
        log_webhook("Hooman", f"Incoming call data: {list(data.keys())}")

        call_info = data.get("callInfo", {})
        phone = call_info.get("to") or data.get("phone", "")
        from_number = call_info.get("from") or data.get("from", "")
        duration = data.get("duration", 0)
        connected = data.get("connected", False)

        # Timestamp
        begin_ts = data.get("beginTimestamp")
        if begin_ts:
            try:
                call_time = datetime.fromisoformat(begin_ts.replace("Z", "+00:00"))
            except Exception:
                call_time = datetime.utcnow()
        else:
            call_time = datetime.utcnow()

        # Status Mapping
        report_status = "Answered " if connected else "Not Answered "

        if connected:
            if duration and int(duration) > 0:
                status = "completed"
            else:
                status = "in-progress"
        else:
            status = "no-answer"

        event = data.get("event", "")
        explicit_status = (
            data.get("Status") or data.get("CallStatus") or data.get("status") or ""
        )
        if explicit_status:
            from app.features.webhooks.routes import _normalise

            status = _normalise(explicit_status)
        elif event:
            event_map = {
                "callEndConnected": "completed",
                "callEndNotConnected": "no-answer",
                "callStart": "ringing",
                "callEnd": "completed",
            }
            status = event_map.get(event, status)

        # Log call report via terminal monitor
        log_activity(
            "CALL",
            f"To:{phone} From:{from_number} Status:{report_status.strip()} "
            f"Duration:{duration}s Connected:{connected}"
        )

        call_uuid = (
            data.get("conversationId")
            or call_info.get("task")
            or call_info.get("callSid")
            or data.get("taskId")
            or data.get("CallUUID")
            or data.get("call_uuid")
            or data.get("call_id")
            or data.get("task_id")
            or data.get("sid")
            or ""
        )
        if isinstance(call_uuid, str):
            call_uuid = call_uuid.strip()

        try:
            import re as _re
            from app.models import DeliveryLog, CampaignTarget

            target = None
            delivery_log = None

            w_conv_id = data.get("conversationId") or ""
            w_task_id = data.get("taskId") or call_info.get("task") or ""
            w_phone = phone or data.get("phone") or ""

            # Normalize phone once for reuse
            n_phone = ""
            if w_phone:
                n_phone = _re.sub(r'\D', '', w_phone)
                if n_phone.startswith('91') and len(n_phone) == 12:
                    n_phone = n_phone[2:]
                elif len(n_phone) > 10:
                    n_phone = n_phone[-10:]

            # 1. By conversationId → match target or delivery log
            if w_conv_id:
                target = CampaignTarget.query.filter(
                    (CampaignTarget.conversation_id == w_conv_id) |
                    (CampaignTarget.external_task_id == w_conv_id)
                ).first()
                if not target:
                    delivery_log = DeliveryLog.query.filter_by(sid=w_conv_id).first()

            # 2. By taskId
            if not target and not delivery_log and w_task_id:
                target = CampaignTarget.query.filter(
                    (CampaignTarget.conversation_id == w_task_id) |
                    (CampaignTarget.external_task_id == w_task_id)
                ).first()
                if not target:
                    delivery_log = DeliveryLog.query.filter_by(sid=w_task_id).first()

            # 3. By normalized phone — search DeliveryLog recipient (10-digit suffix match)
            if not target and not delivery_log and n_phone:
                delivery_log = DeliveryLog.query.filter(
                    DeliveryLog.channel == "hooman_voice",
                    DeliveryLog.status.in_(["waiting_webhook", "in-progress", "ringing"]),
                    DeliveryLog.recipient.like(f"%{n_phone}")
                ).order_by(DeliveryLog.created_at.desc()).first()

                # Broader search if no active-status log found
                if not delivery_log:
                    delivery_log = DeliveryLog.query.filter(
                        DeliveryLog.channel == "hooman_voice",
                        DeliveryLog.recipient.like(f"%{n_phone}")
                    ).order_by(DeliveryLog.created_at.desc()).first()

            # 4. Cross-link: find matching partner from whichever we found first
            if target and not delivery_log:
                delivery_log = DeliveryLog.query.filter_by(
                    campaign_id=target.campaign_id,
                    record_id=target.record_id
                ).order_by(DeliveryLog.created_at.desc()).first()
            elif delivery_log and not target:
                target = CampaignTarget.query.filter_by(
                    campaign_id=delivery_log.campaign_id,
                    record_id=delivery_log.record_id
                ).filter(
                    CampaignTarget.status.in_(
                        ["calling", "waiting_webhook", "retrying"]
                    )
                ).order_by(CampaignTarget.id.desc()).first()

                # Looser fallback — any non-terminal target for this campaign/record
                if not target:
                    target = CampaignTarget.query.filter_by(
                        campaign_id=delivery_log.campaign_id,
                        record_id=delivery_log.record_id
                    ).order_by(CampaignTarget.id.desc()).first()

            # Bind the new conversationId to the target so future webhooks match instantly
            if target and w_conv_id and target.conversation_id != w_conv_id:
                target.conversation_id = w_conv_id
                db.session.commit()
                log_activity(
                    "WEBHOOK",
                    f"Bound conversationId={w_conv_id} to target={target.id} (phone match)"
                )

            if delivery_log:
                delivery_log.status = status
                meta = dict(delivery_log.meta or {})
                meta["duration_seconds"] = int(duration) if duration else 0
                meta["final_status"] = status
                meta["connected"] = connected
                meta["from_number"] = from_number
                if begin_ts:
                    meta["call_time"] = begin_ts
                delivery_log.meta = meta
                db.session.commit()

                log_activity(
                    "WEBHOOK",
                    f"Updated DeliveryLog #{delivery_log.id} -> status={status}, "
                    f"campaign={delivery_log.campaign_id}, duration={duration}s"
                )

                # ── Hand off to campaign runner for retry/completion logic ──
                try:
                    from app.services.campaign_runner import CampaignExecutionService
                    from flask import current_app
                    _app = current_app._get_current_object()
                    CampaignExecutionService.handle_webhook(_app, data)
                except Exception as _e:
                    log_activity("WEBHOOK", f"Campaign runner handle_webhook error: {_e}", level="error")

            else:
                log_activity(
                    "WEBHOOK",
                    f"No matching DeliveryLog for phone={phone}, uuid={call_uuid}",
                    level="warn"
                )

        except Exception as e:
            log_activity("WEBHOOK", f"Error updating delivery log: {e}", level="error")

        sys.stderr.flush()
        return jsonify({"ok": True}), 200


    # Exempt the global webhook from CSRF
    csrf.exempt(global_webhook)

    # -----------------------------------------------------------------------
    # Voice Note Static File Route
    # Serves MP3 files with explicit Content-Type: audio/mpeg.
    #
    # URL pattern: /static/audio/voice_notes/<campaign_id>_target_<id>.mp3
    # BASE_URL in .env must point to a publicly reachable address.
    # -----------------------------------------------------------------------
    @app.route("/static/audio/voice_notes/<path:filename>")
    def serve_voice_note(filename):
        """Serve MP3 voice notes with the correct Content-Type for WhatsApp."""
        from flask import send_from_directory
        voice_dir = os.path.join(app.root_path, "static", "audio", "voice_notes")
        response  = send_from_directory(voice_dir, filename)
        if filename.lower().endswith(".mp3"):
            response.headers["Content-Type"]        = "audio/mpeg"
            response.headers["Content-Disposition"] = "inline"
            response.headers["Accept-Ranges"]       = "bytes"
        return response

    # Ensure platform admin exists and DB connectivity on startup
    with app.app_context():
        from app.models import PlatformAdmin

        try:
            db.session.execute(text("SELECT 1"))
        except Exception as e:
            raise RuntimeError(f"Unable to connect to the database: {e}")

        # Create tables if they do not exist (for development)
        db.create_all()
        admin = PlatformAdmin.query.filter_by(email=Config.DEFAULT_ADMIN_EMAIL).first()
        if not admin:
            admin = PlatformAdmin.create_default()
            db.session.add(admin)
            db.session.commit()


    @app.context_processor
    def inject_branding():
        from app.models.platform import PlatformBranding
        try:
            branding = PlatformBranding.get_settings()
        except Exception:
            class FakeBranding:
                brand_name = "CalltoConvey"
                logo_path = "logo.jpg"
                logo_display = "both"
                logo_position = "left"
                text_size = 24
                logo_height = 38
                support_email = "support@calltoconvey.io"
                sales_email = "sales@calltoconvey.io"
                billing_email = "billing@calltoconvey.io"
                legal_email = "legal@calltoconvey.io"
                privacy_email = "privacy@calltoconvey.io"
                dpo_email = "dpo@calltoconvey.io"
                contact_phone = "+91 80889 15514"
            branding = FakeBranding()
        return dict(platform_branding=branding)

    @app.template_global()
    def render_brand_logo(height=None, text_size=None, font_color=None):
        from app.models.platform import PlatformBranding
        from flask import url_for
        try:
            b = PlatformBranding.get_settings()
        except Exception:
            class FakeBranding:
                brand_name = "CalltoConvey"
                logo_path = "logo.jpg"
                logo_display = "both"
                logo_position = "left"
                text_size = 24
                logo_height = 38
                support_email = "support@calltoconvey.io"
                sales_email = "sales@calltoconvey.io"
                billing_email = "billing@calltoconvey.io"
                legal_email = "legal@calltoconvey.io"
                privacy_email = "privacy@calltoconvey.io"
                dpo_email = "dpo@calltoconvey.io"
                contact_phone = "+91 80889 15514"
            b = FakeBranding()

        logo_h = height if height is not None else b.logo_height
        text_sz = text_size if text_size is not None else b.text_size
        color_style = f"color: {font_color};" if font_color else ""

        logo_img_tag = ""
        if b.logo_path:
            if '/' in b.logo_path or '\\' in b.logo_path or 'branding/' in b.logo_path:
                img_url = url_for('static', filename=b.logo_path)
            else:
                img_url = url_for('main.static', filename=b.logo_path)
            logo_img_tag = f'<img src="{img_url}" alt="{b.brand_name}" style="height: {logo_h}px; width: auto; object-fit: contain; border-radius: 4px; vertical-align: middle;">'

        text_tag = f'<span style="font-size: {text_sz}px; font-weight: 800; font-family: var(--font-heading); {color_style}">{b.brand_name}</span>'

        if b.logo_display == "logo":
            return logo_img_tag
        elif b.logo_display == "text":
            return text_tag
        else: # both
            gap = "0.5rem"
            flex_dir = "row-reverse" if b.logo_position == "right" else "row"
            return f'<div style="display: inline-flex; align-items: center; gap: {gap}; flex-direction: {flex_dir}; vertical-align: middle;">{logo_img_tag}{text_tag}</div>'

    from app.core.logging_system import log_activity
    log_activity("STARTUP", "APP READY -- All webhooks & routes active")
    log_activity("STARTUP", f"Server: http://0.0.0.0:{os.environ.get('PORT', 5000)}")

    return app

