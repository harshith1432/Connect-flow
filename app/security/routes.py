from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import pyotp
import urllib.parse
from app.extensions import db, csrf
from app.models.security import SecurityAuditLog, MfaConfiguration, ActiveSession
from app.models.worker import OrganizationUser
from app.models.platform import PlatformAdmin
from app.security.mfa import MFAService
from app.security.session_manager import SessionManager
from app.security.rate_limit import limiter
from app.security.auth_protection import PasswordPolicy, BruteForceProtection

security_bp = Blueprint("security", __name__)

def get_current_user_type():
    """
    Helper to check the user type based on model classes.
    """
    if not current_user.is_authenticated:
        return None
    return "platform_admin" if hasattr(current_user, "role") and current_user.role == "platform_owner" else "org_user"

@security_bp.route("/verify-otp", methods=["GET", "POST"])
@limiter.limit("15 per minute")
def verify_otp():
    """
    Renders/checks the OTP verification code during polymorphic login.
    """
    user_id = session.get("pre_mfa_user_id")
    user_type = session.get("pre_mfa_user_type")
    
    if not user_id or not user_type:
        flash("No active authentication flow detected. Please log in.", "warning")
        return redirect(url_for("main.index"))
        
    # Fetch pre-authenticated user
    if user_type == "platform_admin":
        user = PlatformAdmin.query.get(user_id)
        email = user.email if user else ""
        phone = ""
    else:
        user = OrganizationUser.query.get(user_id)
        email = user.email if user else ""
        phone = user.phone if user else ""
        
    config = MFAService.get_mfa_config(user_id, user_type)
    mfa_method = config.mfa_type if config.is_enabled else "email"
    
    # Hide details for security
    masked_email = email[:3] + "..." + email[email.find("@")-2:] if "@" in email else email
    masked_phone = "..." + phone[-4:] if phone else ""

    if request.method == "POST":
        code = request.form.get("otp_code", "").strip()
        
        # Check Brute Force check
        locked, lock_msg = BruteForceProtection.is_locked_out(email)
        if locked:
            flash(lock_msg, "danger")
            return render_template("auth/verify_otp.html", mfa_method=mfa_method, masked_email=masked_email, masked_phone=masked_phone)

        # Validate code or backup code
        is_backup = False
        backup_verified = False
        
        if config.backup_codes and code in config.backup_codes:
            # Verified using backup code
            is_backup = True
            backup_verified = True
            # Remove backup code
            updated_codes = [c for c in config.backup_codes if c != code]
            config.backup_codes = updated_codes
            db.session.commit()
            
            # Log backup code usage
            MFAService._log_audit(user_id, user_type, "Backup Code Verified", "User successfully authenticated with a backup recovery code.")
            
        success = False
        msg = ""
        
        if backup_verified:
            success = True
            msg = "Backup code verified."
        else:
            success, msg = MFAService.verify_otp(user_id, user_type, code)
            
        if success:
            # Login user
            login_user(user, remember=session.get("pre_mfa_remember", False))
            
            # Prevent session fixation
            SessionManager.regenerate_session()
            
            # Track active session in database
            SessionManager.track_session(user.id, user_type)
            
            # Audit successful login
            MFAService._log_audit(user.id, user_type, "User Logged In", f"User logged in successfully via {mfa_method.upper()}.")
            
            # Clear pre-mfa variables
            session.pop("pre_mfa_user_id", None)
            session.pop("pre_mfa_user_type", None)
            session.pop("pre_mfa_remember", None)
            
            flash("Welcome back! Authentication successful.", "success")
            
            # Redirect to dashboards based on polymorphism
            if user_type == "platform_admin":
                return redirect(url_for("super_admin.dashboard"))
            else:
                if user.role == "org_admin":
                    return redirect(url_for("org.dashboard"))
                else:
                    return redirect(url_for("worker.dashboard"))
        else:
            # Log failed attempt
            BruteForceProtection.log_failed_attempt(user_id, user_type, email)
            flash(msg, "danger")
            
    return render_template("auth/verify_otp.html", mfa_method=mfa_method, masked_email=masked_email, masked_phone=masked_phone)


@security_bp.route("/resend-otp", methods=["POST"])
@limiter.limit("3 per minute")
def resend_otp():
    """
    Triggers resending OTP during pre-authenticated status.
    """
    user_id = session.get("pre_mfa_user_id")
    user_type = session.get("pre_mfa_user_type")
    
    if not user_id or not user_type:
        return {"success": False, "message": "No active authentication session."}, 400
        
    config = MFAService.get_mfa_config(user_id, user_type)
    mfa_method = config.mfa_type if config.is_enabled else "email"
    
    if mfa_method == "totp":
        return {"success": False, "message": "Resending is only supported for email or SMS OTPs."}, 400
        
    success, msg = MFAService.generate_and_send_otp(user_id, user_type, method=mfa_method)
    
    if success:
        return {"success": True, "message": "OTP resent successfully."}
    else:
        return {"success": False, "message": msg}, 429


@security_bp.route("/mfa/setup", methods=["GET", "POST"])
@login_required
def mfa_setup():
    """
    Dashboard for setting up multi-factor authentication (Email, SMS, or Google Authenticator TOTP).
    """
    user_id = current_user.id
    user_type = get_current_user_type()
    
    config = MFAService.get_mfa_config(user_id, user_type)
    
    # Generate new secret if they are enabling TOTP and don't have one
    totp_secret = config.secret_key
    if not totp_secret:
        totp_secret = pyotp.random_base32()
        config.secret_key = totp_secret
        db.session.commit()
        
    # Generate provisioning URI
    email = current_user.email
    issuer = "ConnectFlow CRM"
    provisioning_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(name=email, issuer_name=issuer)
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(provisioning_uri)}"

    if request.method == "POST":
        action = request.form.get("action")
        
        # Verify user password for security validation
        password = request.form.get("password", "")
        if not current_user.check_password(password):
            flash("Action rejected. Invalid master password.", "danger")
            return redirect(url_for("security.mfa_setup"))

        if action == "enable_email":
            config.mfa_type = "email"
            config.is_enabled = True
            db.session.commit()
            MFAService._log_audit(user_id, user_type, "MFA Enabled", "Enabled Email-based Multi-Factor Authentication.")
            flash("Email MFA enabled successfully.", "success")
            
        elif action == "enable_sms":
            phone = current_user.phone if hasattr(current_user, "phone") else None
            if not phone:
                flash("SMS MFA requires a registered phone number. Please update your profile.", "danger")
                return redirect(url_for("security.mfa_setup"))
            config.mfa_type = "sms"
            config.is_enabled = True
            db.session.commit()
            MFAService._log_audit(user_id, user_type, "MFA Enabled", "Enabled SMS-based Multi-Factor Authentication.")
            flash("SMS MFA enabled successfully.", "success")
            
        elif action == "enable_totp":
            totp_code = request.form.get("totp_code", "").strip()
            totp = pyotp.TOTP(totp_secret)
            
            if totp.verify(totp_code, valid_window=1):
                config.mfa_type = "totp"
                config.is_enabled = True
                
                # Generate new backup codes upon first TOTP enabling
                backup_codes = MFAService.generate_backup_codes()
                config.backup_codes = backup_codes
                
                db.session.commit()
                
                MFAService._log_audit(user_id, user_type, "MFA Enabled", "Enabled Google Authenticator (TOTP) Multi-Factor Authentication.")
                session["backup_codes_display"] = backup_codes
                flash("Google Authenticator setup verified and enabled successfully!", "success")
                return redirect(url_for("security.mfa_setup"))
            else:
                flash("Invalid Google Authenticator code. Please scan the QR code and try again.", "danger")
                
        elif action == "disable":
            config.mfa_type = "none"
            config.is_enabled = False
            config.backup_codes = None
            db.session.commit()
            MFAService._log_audit(user_id, user_type, "MFA Disabled", "Disabled Multi-Factor Authentication.")
            flash("Multi-Factor Authentication has been disabled.", "warning")
            
        elif action == "regenerate_backup":
            if config.mfa_type == "totp" and config.is_enabled:
                backup_codes = MFAService.generate_backup_codes()
                config.backup_codes = backup_codes
                db.session.commit()
                session["backup_codes_display"] = backup_codes
                flash("Backup recovery codes regenerated successfully.", "info")
            else:
                flash("Backup recovery codes are only available for Authenticator (TOTP) MFA.", "warning")
                
        return redirect(url_for("security.mfa_setup"))

    backup_codes_display = session.pop("backup_codes_display", None)
    
    return render_template(
        "security/mfa_setup.html", 
        config=config, 
        totp_secret=totp_secret, 
        qr_code_url=qr_code_url,
        backup_codes_display=backup_codes_display
    )


@security_bp.route("/sessions", methods=["GET"])
@login_required
def sessions():
    """
    Renders active sessions dashboard for user auditing.
    """
    user_id = current_user.id
    user_type = get_current_user_type()
    
    active_list = SessionManager.get_active_sessions(user_id, user_type)
    current_token = session.get("_session_token")
    
    return render_template(
        "security/sessions.html", 
        sessions=active_list, 
        current_token=current_token
    )


@security_bp.route("/sessions/revoke/<token>", methods=["POST"])
@login_required
def revoke_session(token):
    """
    Terminates a specific remote session.
    """
    user_id = current_user.id
    user_type = get_current_user_type()
    
    # Verify token belongs to user
    sess = ActiveSession.query.filter_by(session_token=token, user_id=user_id, user_type=user_type).first()
    if not sess:
        flash("Invalid session token or access unauthorized.", "danger")
        return redirect(url_for("security.sessions"))
        
    current_token = session.get("_session_token")
    SessionManager.terminate_session(token)
    
    if token == current_token:
        # User terminated their own current session
        SessionManager.logout_and_clean()
        flash("You terminated your current session and have been logged out.", "warning")
        return redirect(url_for("main.index"))
        
    flash("Remote session revoked successfully.", "success")
    return redirect(url_for("security.sessions"))


@security_bp.route("/audit-logs", methods=["GET"])
@login_required
def audit_logs():
    """
    Visualizes audit trail logs for enterprise transparency.
    """
    user_id = current_user.id
    user_type = get_current_user_type()
    
    # Query logs
    logs = SecurityAuditLog.query.filter_by(user_id=user_id, user_type=user_type).order_by(SecurityAuditLog.created_at.desc()).limit(100).all()
    
    return render_template("security/audit_logs.html", logs=logs)
