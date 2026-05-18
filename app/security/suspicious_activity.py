import sys
from datetime import datetime, timedelta
from flask import request, session
from app.extensions import db
from app.models.security import ActiveSession, SuspiciousActivity, SecurityAuditLog
from app.security.session_manager import SessionManager

class SuspiciousActivityMonitor:
    @staticmethod
    def monitor_current_request(user_id, user_type):
        """
        Monitors the current request for suspicious patterns (like IP switching or session hijacking).
        Should be called in app.before_request if the user is authenticated.
        """
        token = session.get("_session_token")
        if not token:
            return True  # Managed by session enforcement if missing
            
        active_sess = ActiveSession.query.filter_by(session_token=token).first()
        if not active_sess:
            return True
            
        current_ip = request.remote_addr
        
        # 1. Detect Session Hijacking / IP Spoofing
        # If the IP changes radically from the one that logged in, raise a high severity alert
        if active_sess.ip_address and active_sess.ip_address != current_ip:
            # Check if both are localhost for dev testing
            is_local_switch = (current_ip in ["127.0.0.1", "::1"]) and (active_sess.ip_address in ["127.0.0.1", "::1"])
            
            if not is_local_switch:
                sys.stderr.write(f"[SECURITY WARNING] IP switch detected for user {user_id} ({user_type})! Session IP: {active_sess.ip_address}, Request IP: {current_ip}\n")
                
                # Log suspicious activity
                s = SuspiciousActivity(
                    user_id=user_id,
                    user_type=user_type,
                    ip_address=current_ip,
                    activity_type="session_ip_mismatch",
                    details=f"Active session IP switch detected. Session IP: {active_sess.ip_address}, Request IP: {current_ip}. Terminating session for security."
                )
                db.session.add(s)
                
                # Terminate the compromised session immediately
                SessionManager.logout_and_clean()
                db.session.commit()
                return False
                
        # 2. Check for simultaneous logins (optional warning/audit)
        # If a user is logging in from multiple distinct IPs concurrently
        distinct_ips = db.session.query(ActiveSession.ip_address).filter_by(
            user_id=user_id,
            user_type=user_type
        ).distinct().all()
        
        if len(distinct_ips) > 3:
            # Too many concurrent distinct IPs
            s = SuspiciousActivity(
                user_id=user_id,
                user_type=user_type,
                ip_address=current_ip,
                activity_type="multiple_concurrent_ips",
                details=f"User is logged in from {len(distinct_ips)} distinct IPs concurrently."
            )
            db.session.add(s)
            db.session.commit()
            
        return True
