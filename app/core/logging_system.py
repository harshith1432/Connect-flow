"""
Real-Time Terminal Activity Monitor
====================================
Shows every HTTP request, response, DB query, error, and webhook event
in a clean, single-line, color-coded format -- flushed immediately
so it appears in the terminal in real time (Windows compatible).
"""

import os
import sys
import time
import json
import logging
import traceback
from logging.handlers import RotatingFileHandler
from flask import request, g, current_app
from datetime import datetime


# ---------------------------------------------------------------
# ANSI Colors (Windows 10+ Terminal supports these)
# ---------------------------------------------------------------
class C:
    """Terminal color codes."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"

    # Methods
    GET     = "\033[38;5;39m"    # Blue
    POST    = "\033[38;5;208m"   # Orange
    PUT     = "\033[38;5;226m"   # Yellow
    PATCH   = "\033[38;5;183m"   # Light purple
    DELETE  = "\033[38;5;196m"   # Red

    # Status codes
    OK      = "\033[38;5;46m"    # Green
    WARN    = "\033[38;5;226m"   # Yellow
    ERR     = "\033[38;5;196m"   # Red
    REDIR   = "\033[38;5;51m"    # Cyan

    # Events
    DB      = "\033[38;5;141m"   # Purple
    WEBHOOK = "\033[38;5;214m"   # Gold
    AUTH    = "\033[38;5;123m"   # Light cyan
    ERROR   = "\033[38;5;196m"   # Red
    STARTUP = "\033[38;5;46m"    # Green
    INFO    = "\033[38;5;252m"   # Light gray
    TIME    = "\033[38;5;245m"   # Gray
    PATH    = "\033[38;5;255m"   # White


# Enable ANSI colors on Windows
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Enable virtual terminal processing on stdout and stderr
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)  # stdout
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-12), 7)  # stderr
    except Exception:
        pass


def _out(msg):
    """Write to stderr and flush immediately -- real-time on Windows."""
    # Encode safely for Windows console (replace unencodable chars)
    try:
        enc = sys.stderr.encoding or 'utf-8'
        safe_msg = msg.encode(enc, errors='replace').decode(enc, errors='replace')
    except Exception:
        safe_msg = msg
    sys.stderr.write(safe_msg + "\n")
    sys.stderr.flush()
    # Also write plain-text version to activity.log (strip ANSI codes)
    try:
        import re
        plain = re.sub(r'\033\[[0-9;]*m', '', msg).strip()
        if plain:
            with open("logs/activity.log", "a", encoding="utf-8") as f:
                f.write(plain + "\n")
    except Exception:
        pass


def _method_color(method):
    """Return ANSI color for an HTTP method."""
    return {
        "GET":    C.GET,
        "POST":   C.POST,
        "PUT":    C.PUT,
        "PATCH":  C.PATCH,
        "DELETE": C.DELETE,
    }.get(method, C.INFO)


def _status_color(code):
    """Return ANSI color for an HTTP status code."""
    if 200 <= code < 300:
        return C.OK
    elif 300 <= code < 400:
        return C.REDIR
    elif 400 <= code < 500:
        return C.WARN
    else:
        return C.ERR


def _status_icon(code):
    """Return a status icon for quick scanning (ASCII safe)."""
    if 200 <= code < 300:
        return "[OK]"
    elif 300 <= code < 400:
        return "[->]"
    elif 400 <= code < 500:
        return "[!!]"
    else:
        return "[XX]"


def mask_secrets(data):
    """Mask sensitive values in dictionaries or lists for safe logging."""
    if isinstance(data, list):
        return [mask_secrets(item) for item in data]
    if not isinstance(data, dict):
        return data
    masked = {}
    secret_keys = ['password', 'token', 'secret', 'key', 'auth', 'api_key', 'apikey', 'credential', 'hash', 'signature']
    for k, v in data.items():
        if any(s in k.lower() for s in secret_keys):
            if isinstance(v, str) and len(v) > 4:
                masked[k] = v[:4] + "***"
            else:
                masked[k] = "***"
        elif isinstance(v, (dict, list)):
            masked[k] = mask_secrets(v)
        else:
            masked[k] = v
    return masked


def _print_banner():
    """Print startup banner (ASCII safe for Windows)."""
    _out("")
    _out(f"{C.STARTUP}{C.BOLD}+{'='*62}+{C.RESET}")
    _out(f"{C.STARTUP}{C.BOLD}|     REAL-TIME TERMINAL ACTIVITY MONITOR                      |{C.RESET}")
    _out(f"{C.STARTUP}{C.BOLD}|     All HTTP / DB / Webhook activity shown below              |{C.RESET}")
    _out(f"{C.STARTUP}{C.BOLD}+{'='*62}+{C.RESET}")
    _out("")
    _out(f"  {C.DIM}Legend:{C.RESET}  "
         f"{C.GET}GET{C.RESET}  "
         f"{C.POST}POST{C.RESET}  "
         f"{C.PUT}PUT{C.RESET}  "
         f"{C.DELETE}DELETE{C.RESET}  "
         f"{C.OK}2xx{C.RESET}  "
         f"{C.WARN}4xx{C.RESET}  "
         f"{C.ERR}5xx{C.RESET}  "
         f"{C.DB}DB{C.RESET}  "
         f"{C.WEBHOOK}WEBHOOK{C.RESET}")
    _out(f"  {C.DIM}{'-' * 62}{C.RESET}")
    _out("")


def setup_full_debug_logging(app):
    """
    Initialize the real-time terminal activity monitor.

    Shows:
    - Every HTTP request (method, path, user, body summary)
    - Every HTTP response (status, duration)
    - Database queries (slow or write operations)
    - Webhook events
    - Errors with tracebacks
    """

    # ---------------------------------------------------------------
    # 1. FILE LOGGING (detailed logs to file)
    # ---------------------------------------------------------------
    if not os.path.exists("logs"):
        os.makedirs("logs")

    if os.name == 'nt' and app.debug:
        # Avoid WinError 32 on Windows with Werkzeug reloader
        file_handler = logging.FileHandler("logs/app.log", encoding="utf-8")
    else:
        file_handler = RotatingFileHandler(
            "logs/app.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
    )
    file_handler.setFormatter(file_formatter)

    app.logger.setLevel(logging.DEBUG)
    app.logger.addHandler(file_handler)

    # ---------------------------------------------------------------
    # 2. PRINT STARTUP BANNER
    # ---------------------------------------------------------------
    _print_banner()

    # ---------------------------------------------------------------
    # 3. REQUEST LOGGING -- fires on every incoming request
    # ---------------------------------------------------------------
    @app.before_request
    def terminal_log_request():
        # Skip static files
        if request.path.startswith("/static"):
            return

        g.req_start_time = time.time()
        g.req_timestamp = time.strftime("%H:%M:%S")

        # Collect request details for terminal
        method = request.method
        path = request.path
        mc = _method_color(method)

        # User identification
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                user_info = f"user:{current_user.id}"
            else:
                user_info = "guest"
        except Exception:
            user_info = "guest"

        # Body summary (compact)
        body_summary = ""
        try:
            json_data = request.get_json(silent=True)
            if json_data:
                masked = mask_secrets(json_data)
                keys = list(masked.keys())[:5]
                body_summary = f" body={{{', '.join(keys)}}}"
        except Exception:
            pass

        if not body_summary:
            form_data = request.form.to_dict()
            if form_data:
                masked = mask_secrets(form_data)
                keys = list(masked.keys())[:5]
                body_summary = f" form={{{', '.join(keys)}}}"

        # Query params
        query_summary = ""
        if request.args:
            params = list(request.args.keys())[:3]
            query_summary = f" ?{','.join(params)}"

        # Print the request line
        _out(
            f"  {C.TIME}{g.req_timestamp}{C.RESET}  "
            f"{mc}{C.BOLD}--> {method:6s}{C.RESET}  "
            f"{C.PATH}{path}{query_summary}{C.RESET}  "
            f"{C.DIM}[{user_info}]{body_summary}{C.RESET}"
        )

        # Detailed file log
        app.logger.debug(
            f"REQUEST {method} {request.url} user={user_info}{body_summary}"
        )

    # ---------------------------------------------------------------
    # 4. RESPONSE LOGGING -- fires after every response
    # ---------------------------------------------------------------
    @app.after_request
    def terminal_log_response(response):
        if request.path.startswith("/static"):
            return response

        status = response.status_code
        sc = _status_color(status)
        icon = _status_icon(status)

        # Duration
        duration_str = ""
        if hasattr(g, 'req_start_time'):
            duration_ms = int((time.time() - g.req_start_time) * 1000)
            if duration_ms > 1000:
                duration_str = f" {C.WARN}{duration_ms}ms SLOW!{C.RESET}"
            elif duration_ms > 500:
                duration_str = f" {C.WARN}{duration_ms}ms{C.RESET}"
            else:
                duration_str = f" {C.DIM}{duration_ms}ms{C.RESET}"

        ts = getattr(g, 'req_timestamp', time.strftime("%H:%M:%S"))

        # Content size
        size_str = ""
        if response.content_length:
            size_kb = response.content_length / 1024
            if size_kb >= 1:
                size_str = f" {C.DIM}{size_kb:.1f}KB{C.RESET}"

        _out(
            f"  {C.TIME}{ts}{C.RESET}  "
            f"{sc}{C.BOLD}<-- {icon} {status}{C.RESET}  "
            f"{C.DIM}{request.method} {request.path}{C.RESET}"
            f"{duration_str}{size_str}"
        )

        # Detailed file log
        app.logger.debug(
            f"RESPONSE {status} {request.method} {request.path}"
        )

        return response

    # ---------------------------------------------------------------
    # 5. ERROR LOGGING -- catches all unhandled exceptions
    # ---------------------------------------------------------------
    @app.errorhandler(Exception)
    def terminal_log_error(e):
        ts = time.strftime("%H:%M:%S")
        tb = traceback.format_exc()

        # Terminal: show error prominently
        _out("")
        _out(f"  {C.ERROR}{C.BOLD}{'=' * 60}{C.RESET}")
        _out(
            f"  {C.TIME}{ts}{C.RESET}  "
            f"{C.ERROR}{C.BOLD}[XX] ERROR{C.RESET}  "
            f"{C.PATH}{request.method} {request.path}{C.RESET}"
        )
        _out(f"  {C.ERROR}  Exception: {type(e).__name__}: {str(e)}{C.RESET}")

        # Show last 3 relevant traceback lines
        tb_lines = [l for l in tb.strip().split("\n") if l.strip()]
        for line in tb_lines[-3:]:
            _out(f"  {C.DIM}  {line.strip()}{C.RESET}")

        _out(f"  {C.ERROR}{C.BOLD}{'=' * 60}{C.RESET}")
        _out("")

        # Detailed file log
        app.logger.error(
            f"ERROR {request.method} {request.url}\n"
            f"Exception: {str(e)}\n{tb}"
        )

        # Re-raise HTTP exceptions (404, 405, etc.)
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        return "Internal Server Error", 500

    # ---------------------------------------------------------------
    # 6. DB QUERY LOGGING (via SQLAlchemy events)
    # ---------------------------------------------------------------
    try:
        from sqlalchemy import event
        from app.extensions import db as _db

        @event.listens_for(_db.engine.__class__, "before_cursor_execute", named=True)
        def _log_query_start(**kw):
            conn = kw.get("conn")
            if conn:
                conn.info.setdefault("query_start_time", []).append(time.time())

        @event.listens_for(_db.engine.__class__, "after_cursor_execute", named=True)
        def _log_query_end(**kw):
            conn = kw.get("conn")
            statement = kw.get("statement", "")
            if conn and conn.info.get("query_start_time"):
                start = conn.info["query_start_time"].pop()
                duration_ms = int((time.time() - start) * 1000)

                # Truncate long queries
                stmt_short = statement.strip().replace("\n", " ")[:80]

                # Only log slow queries (>100ms) or write operations to terminal
                is_write = any(
                    stmt_short.upper().startswith(k)
                    for k in ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
                )
                if duration_ms > 100 or is_write:
                    ts = time.strftime("%H:%M:%S")
                    speed = f"{C.WARN}SLOW " if duration_ms > 500 else ""
                    _out(
                        f"  {C.TIME}{ts}{C.RESET}  "
                        f"{C.DB}[DB]{C.RESET}  "
                        f"{speed}{C.DIM}{stmt_short}{C.RESET}  "
                        f"{C.DIM}{duration_ms}ms{C.RESET}"
                    )
    except Exception:
        # DB event listeners may fail during app init -- that's OK
        pass

    # ---------------------------------------------------------------
    # 7. CUSTOM LOG HELPERS (importable by other modules)
    # ---------------------------------------------------------------
    app.terminal_log = _out
    app.terminal_colors = C


# ---------------------------------------------------------------
# PUBLIC HELPERS -- can be imported anywhere
# ---------------------------------------------------------------

def log_activity(category, message, level="info"):
    """
    Log a custom activity to the terminal.

    Usage:
        from app.core.logging_system import log_activity
        log_activity("WEBHOOK", "Received call status update for +91...")
        log_activity("AUTH", "User admin@test.com logged in")
        log_activity("CAMPAIGN", "Started campaign #42 with 150 contacts")
        log_activity("ERROR", "WhatsApp API timeout", level="error")
    """
    ts = time.strftime("%H:%M:%S")

    color_map = {
        "WEBHOOK":  C.WEBHOOK,
        "AUTH":     C.AUTH,
        "DB":       C.DB,
        "ERROR":    C.ERROR,
        "STARTUP":  C.STARTUP,
    }
    cat_color = color_map.get(category.upper(), C.INFO)

    if level == "error":
        _out(
            f"  {C.TIME}{ts}{C.RESET}  "
            f"{C.ERROR}{C.BOLD}[XX] {category.upper()}{C.RESET}  "
            f"{C.ERROR}{message}{C.RESET}"
        )
    elif level == "warn":
        _out(
            f"  {C.TIME}{ts}{C.RESET}  "
            f"{C.WARN}[!!] {category.upper()}{C.RESET}  "
            f"{message}"
        )
    else:
        _out(
            f"  {C.TIME}{ts}{C.RESET}  "
            f"{cat_color}[*] {category.upper()}{C.RESET}  "
            f"{message}"
        )


def log_webhook(source, data_summary):
    """Log webhook events with special formatting."""
    ts = time.strftime("%H:%M:%S")
    _out(
        f"  {C.TIME}{ts}{C.RESET}  "
        f"{C.WEBHOOK}{C.BOLD}[>>] WEBHOOK{C.RESET}  "
        f"{C.WEBHOOK}{source}{C.RESET}  "
        f"{C.DIM}{data_summary}{C.RESET}"
    )


def log_api_call(service, endpoint, status="ok"):
    """Log outbound API calls (e.g., to WhatsApp, Hooman)."""
    ts = time.strftime("%H:%M:%S")
    icon = f"{C.OK}[OK]" if status == "ok" else f"{C.ERR}[XX]"
    _out(
        f"  {C.TIME}{ts}{C.RESET}  "
        f"{C.POST}[API-OUT]{C.RESET}  "
        f"{C.PATH}{service}{C.RESET} -> {endpoint}  "
        f"{icon}{C.RESET}"
    )
