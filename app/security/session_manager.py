import os
import sys
import secrets
from datetime import datetime, timedelta
from flask import session, request, redirect, url_for, flash, current_app
from flask_login import current_user, logout_user
from app.extensions import db
from app.models.security import ActiveSession, SecurityAuditLog

class SessionManager:
    TIMEOUT_MINUTES = 20

    @staticmethod
    def regenerate_session():
        """
        Regenerate the session identifier to prevent Session Fixation attacks.
        Copies existing session data, clears the old session, and populates the new session.
        """
        # Save old data
        old_data = dict(session)
        # Clear old session
        session.clear()
        # Renew session cookie parameters and copy back data
        for key, value in old_data.items():
            session[key] = value
        # Add a fresh session key for database tracking
        session["_session_token"] = secrets.token_urlsafe(32)
        session.modified = True
        return session["_session_token"]

    @staticmethod
    def track_session(user_id, user_type):
        """
        Register or update the active session metadata in the database.
        Includes device tracking (user-agent parsing, IP address, etc.).
        """
        token = session.get("_session_token")
        if not token:
            token = SessionManager.regenerate_session()

        # Parse user agent
        ua_string = request.user_agent.string if request.user_agent else "Unknown"
        browser = request.user_agent.browser if request.user_agent else "Unknown"
        os_platform = request.user_agent.platform if request.user_agent else "Unknown"
        
        # Simple device estimation
        device = "Desktop"
        if request.user_agent and any(word in ua_string.lower() for word in ["mobi", "android", "iphone", "ipad"]):
            device = "Mobile"

        # Check if session token exists in DB
        active_sess = ActiveSession.query.filter_by(session_token=token).first()
        now = datetime.utcnow()

        if active_sess:
            active_sess.last_activity = now
            active_sess.ip_address = request.remote_addr
            active_sess.user_agent = ua_string[:500]
        else:
            active_sess = ActiveSession(
                user_id=user_id,
                user_type=user_type,
                session_token=token,
                ip_address=request.remote_addr,
                user_agent=ua_string[:500],
                browser=browser,
                device=device,
                os=os_platform,
                last_activity=now,
                created_at=now
            )
            db.session.add(active_sess)

        db.session.commit()

    @staticmethod
    def enforce_session_timeout():
        """
        Enforce absolute inactivity timeouts (20 minutes).
        To be run inside before_request handler.
        """
        # Exclude static assets
        if request.path.startswith("/static/") or request.path.startswith("/static"):
            return

        if not current_user.is_authenticated:
            return

        # Check if token in session
        token = session.get("_session_token")
        if not token:
            # Missing token in authenticated session -> force logout for safety
            SessionManager.logout_and_clean()
            flash("Session security token missing. Please log in again.", "warning")
            return redirect(url_for("main.index"))

        active_sess = ActiveSession.query.filter_by(session_token=token).first()
        now = datetime.utcnow()

        if not active_sess:
            # Active session was deleted from backend (force logged out by admin or password change)
            SessionManager.logout_and_clean()
            flash("Your session has been terminated by an administrator or a security event.", "danger")
            return redirect(url_for("main.index"))

        # Calculate time difference
        diff = now - active_sess.last_activity
        if diff > timedelta(minutes=SessionManager.TIMEOUT_MINUTES):
            # Session timed out
            db.session.delete(active_sess)
            db.session.commit()
            
            # Log audit
            audit = SecurityAuditLog(
                user_id=current_user.id,
                user_type="platform_admin" if hasattr(current_user, "role") and current_user.role == "platform_owner" else "org_user",
                action="session_timeout",
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string if request.user_agent else "Unknown",
                details={"message": f"Session timed out due to inactivity after {SessionManager.TIMEOUT_MINUTES} minutes."},
                severity="low"
            )
            db.session.add(audit)
            db.session.commit()

            SessionManager.logout_and_clean()
            flash(f"You have been logged out due to inactivity for {SessionManager.TIMEOUT_MINUTES} minutes.", "info")
            return redirect(url_for("main.index"))

        # Update last activity
        active_sess.last_activity = now
        db.session.commit()

    @staticmethod
    def terminate_session(token):
        """
        Manually delete a session from DB (causing logout on next request).
        """
        active_sess = ActiveSession.query.filter_by(session_token=token).first()
        if active_sess:
            # Log audit
            audit = SecurityAuditLog(
                user_id=active_sess.user_id,
                user_type=active_sess.user_type,
                action="session_terminated",
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string if request.user_agent else "Unknown",
                details={"message": f"Session token {token[:10]}... terminated manually."},
                severity="medium"
            )
            db.session.add(audit)
            db.session.delete(active_sess)
            db.session.commit()
            return True
        return False

    @staticmethod
    def terminate_all_user_sessions(user_id, user_type, except_token=None):
        """
        Terminate all sessions associated with a user.
        Useful on password change, compromise, or lockout.
        """
        query = ActiveSession.query.filter_by(user_id=user_id, user_type=user_type)
        if except_token:
            query = query.filter(ActiveSession.session_token != except_token)
        
        sessions_to_kill = query.all()
        for s in sessions_to_kill:
            db.session.delete(s)
            
        audit = SecurityAuditLog(
            user_id=user_id,
            user_type=user_type,
            action="all_sessions_terminated",
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else "Unknown",
            details={"message": f"All sessions terminated. except_token={except_token is not None}"},
            severity="medium"
        )
        db.session.add(audit)
        db.session.commit()

    @staticmethod
    def logout_and_clean():
        """
        Safely log out Flask-Login and clear session dictionary.
        """
        token = session.get("_session_token")
        if token:
            active_sess = ActiveSession.query.filter_by(session_token=token).first()
            if active_sess:
                db.session.delete(active_sess)
                db.session.commit()
        logout_user()
        session.clear()

    @staticmethod
    def get_active_sessions(user_id, user_type):
        """
        List all active sessions of a user.
        """
        return ActiveSession.query.filter_by(user_id=user_id, user_type=user_type).all()
