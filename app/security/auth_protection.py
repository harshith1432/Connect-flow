import re
from datetime import datetime, timedelta
from flask import request
from app.extensions import db
from app.models.security import SecurityAuditLog, SuspiciousActivity


class PasswordPolicy:
    @staticmethod
    def validate_password(password):
        """
        Validates password against enterprise complexity requirements:
        - Minimum 10 characters
        - Contains at least 1 uppercase letter
        - Contains at least 1 lowercase letter
        - Contains at least 1 number
        - Contains at least 1 special character
        """
        if len(password) < 10:
            return False, "Password must be at least 10 characters long."

        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter."

        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter."

        if not re.search(r"\d", password):
            return False, "Password must contain at least one number."

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False, "Password must contain at least one special character."

        return True, "Password is valid."


class BruteForceProtection:
    MAX_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15

    @staticmethod
    def is_locked_out(identifier):
        """
        Checks if the IP or username is locked out due to repeated failed logins.
        Query security audit log for 'login_failed' actions in the last LOCKOUT_MINUTES.
        """
        ip = request.remote_addr
        lockout_time = datetime.utcnow() - timedelta(
            minutes=BruteForceProtection.LOCKOUT_MINUTES
        )

        # Count failed logins from this IP
        failed_count_ip = SecurityAuditLog.query.filter(
            SecurityAuditLog.action == "login_failed",
            SecurityAuditLog.ip_address == ip,
            SecurityAuditLog.created_at >= lockout_time,
        ).count()

        if failed_count_ip >= BruteForceProtection.MAX_ATTEMPTS:
            # Check if we already logged a suspicious activity for this lockout
            suspicious = (
                SuspiciousActivity.query.filter_by(
                    ip_address=ip, activity_type="brute_force_lockout"
                )
                .filter(SuspiciousActivity.created_at >= lockout_time)
                .first()
            )

            if not suspicious:
                # Log IP block as suspicious activity
                s = SuspiciousActivity(
                    ip_address=ip,
                    activity_type="brute_force_lockout",
                    details=f"IP locked out after {failed_count_ip} failed login attempts. Target: {identifier}",
                )
                db.session.add(s)
                db.session.commit()

            return (
                True,
                f"This IP has been temporarily locked out due to multiple failed login attempts. Please try again in {BruteForceProtection.LOCKOUT_MINUTES} minutes.",
            )

        return False, None

    @staticmethod
    def log_failed_attempt(user_id=None, user_type=None, identifier=None):
        """
        Record a failed login attempt in the SecurityAuditLog.
        """
        audit = SecurityAuditLog(
            user_id=user_id,
            user_type=user_type,
            action="login_failed",
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else "Unknown",
            details={
                "message": f"Failed login attempt for identifier: {identifier}",
                "identifier": identifier,
            },
            severity="medium",
        )
        db.session.add(audit)
        db.session.commit()
