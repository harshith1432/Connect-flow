import os
import platform
import sys
import time
import logging

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

    # Configure root logger to output EVERYTHING to stderr (bypasses Windows stdout buffering)
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(stderr_handler)
    root.setLevel(logging.INFO)

    # Fix Werkzeug logger which suppresses logs by default in newer versions
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addHandler(stderr_handler)
    werkzeug_logger.propagate = False  # Prevent double logging

    # WSGI Middleware for absolute lowest-level logging
    class RequestLoggerMiddleware:
        def __init__(self, app_app):
            self.app_app = app_app

        def __call__(self, environ, start_response):
            method = environ.get("REQUEST_METHOD")
            path = environ.get("PATH_INFO")
            query = environ.get("QUERY_STRING")
            full_path = f"{path}?{query}" if query else path
            print(f"\n[WSGI-IN] {method} {full_path}", flush=True)
            return self.app_app(environ, start_response)

    app.wsgi_app = RequestLoggerMiddleware(app.wsgi_app)

    @app.before_request
    def start_timer():
        # Double-check logging for Flask context
        print(f"[FLASK-BEFORE] {request.method} {request.path}", flush=True)
        g.start = time.time()

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
    def log_and_secure_request(response):
        # Add Cache-Control headers to prevent browser back-button caching
        if not request.path.startswith("/static"):
            response.headers[
                "Cache-Control"
            ] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        if hasattr(g, "start"):
            diff = time.time() - g.start
            print(
                f"[FLASK-AFTER] {request.method} {request.path} -> {response.status_code} ({diff:.4f}s)",
                flush=True,
            )
        return response

    # Initialize DB, Migrate and Login
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.index"

    # Initialize rate limiting and security headers
    from app.security.rate_limit import init_rate_limiting
    from app.security.security_headers import init_security_headers

    init_rate_limiting(app)
    init_security_headers(app)

    # loader: try platform admin then organization users
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import PlatformAdmin, OrganizationUser

        u = db.session.get(PlatformAdmin, int(user_id))
        if u:
            return u
        return db.session.get(OrganizationUser, int(user_id))

    # Register blueprints
    from app.features.public import main_bp
    from app.features.super_admin import super_admin_bp
    from app.features.tenant_admin import org_bp
    from app.features.workforce import worker_bp
    from app.features.api import api_bp
    from app.features.webhooks import webhooks_bp
    from app.security.routes import security_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(security_bp, url_prefix="/security")

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

        # Log incoming webhook
        print(f"\n{'='*60}", file=sys.stderr)
        print(
            f"[WEBHOOK] Incoming request at {time.strftime('%Y-%m-%d %H:%M:%S')}",
            file=sys.stderr,
        )
        print(f"[DATA]: {data}", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        sys.stderr.flush()

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

        # Print result in user's requested format
        print("\n" + " CALL REPORT")
        print(f"To: {phone}")
        print(f"From: {from_number}")
        print(f"Status: {report_status}")
        print(f"Duration: {duration}")
        print(f"Connected: {connected}")
        print(f"Time: {call_time}")
        print("=" * 40 + "\n")
        sys.stdout.flush()

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
        )
        if isinstance(call_uuid, str):
            call_uuid = call_uuid.strip()

        try:
            from app.models import DeliveryLog

            delivery_log = None

            if call_uuid:
                delivery_log = DeliveryLog.query.filter_by(sid=call_uuid).first()

            if not delivery_log and phone:
                delivery_log = (
                    DeliveryLog.query.filter_by(recipient=phone, channel="hooman_voice")
                    .order_by(DeliveryLog.created_at.desc())
                    .first()
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

                print(
                    f"[WEBHOOK] Updated DeliveryLog #{delivery_log.id} -> status={status}, "
                    f"campaign={delivery_log.campaign_id}, duration={duration}s",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[WEBHOOK] No matching DeliveryLog found for phone={phone}, uuid={call_uuid}",
                    file=sys.stderr,
                )

        except Exception as e:
            print(f"[WEBHOOK] Error updating delivery log: {e}", file=sys.stderr)

        sys.stderr.flush()
        return jsonify({"ok": True}), 200

    # Exempt the global webhook from CSRF
    csrf.exempt(global_webhook)

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

    print("\n" + "*" * 60, file=sys.stderr)
    print("APP READY: ANTIGRAVITY HOOMAN WEBHOOKS ENABLED", file=sys.stderr)
    print("*" * 60 + "\n", file=sys.stderr)
    sys.stderr.flush()

    return app
