from functools import wraps
from flask import redirect, url_for, flash, request
from flask_login import current_user, login_required


def platform_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # Platform admin is a different model; detect by class name to avoid circular imports
        if current_user.__class__.__name__ != "PlatformAdmin":
            flash("Access denied: platform owner only", "danger")
            return redirect(
                url_for("super_admin.login")
            )  # Updated to the new blueprint name later
        return f(*args, **kwargs)

    return decorated


def org_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not hasattr(current_user, "organization_id") or getattr(current_user, "role", "") != "org_admin":
            flash("Access denied: organization admins only", "danger")
            return redirect(url_for("org.login"))
        return f(*args, **kwargs)

    return decorated


def verified_org_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not hasattr(current_user, "organization_id") or getattr(current_user, "role", "") != "org_admin":
            flash("Access denied: organization admins only", "danger")
            return redirect(url_for("org.login"))
        return f(*args, **kwargs)

    return decorated


def worker_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if (
            not hasattr(current_user, "organization_id")
            or getattr(current_user, "role", "") != "worker"
        ):
            flash("Access denied: worker only", "danger")
            return redirect(url_for("worker.login"))
        return f(*args, **kwargs)

    return decorated


def campaign_express_required(f):
    """Guard for Campaign Express users (role='campaign_express')."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if getattr(current_user, "role", "") != "campaign_express":
            flash("Access denied: Campaign Express users only", "danger")
            return redirect(url_for("campaign_express.login"))
        return f(*args, **kwargs)

    return decorated


def active_subscription_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # Platform admin is exempt
        if current_user.__class__.__name__ == "PlatformAdmin":
            return f(*args, **kwargs)

        if not hasattr(current_user, "organization_id"):
            return f(*args, **kwargs)

        from app.models import Subscription
        from datetime import datetime, timedelta

        sub = Subscription.query.filter_by(
            organization_id=current_user.organization_id
        ).first()

        # MANDATORY: If no subscription record, they must buy one
        if not sub:
            allowed_endpoints = [
                "org.browse_plans",
                "org.checkout",
                "org.process_payment",
                "org.logout",
            ]
            if request.endpoint not in allowed_endpoints:
                if getattr(current_user, "role", "") == "worker":
                    return redirect(url_for("main.subscription_expired"))

                flash(
                    "A subscription is required to access these features. Please choose a plan.",
                    "warning",
                )
                return redirect(url_for("org.browse_plans"))
            return f(*args, **kwargs)

        now = datetime.utcnow()

        # Automatic transition/downgrade to Free Trial on subscription expiry
        if sub.expires_at and now > sub.expires_at and sub.plan != "Free Trial":
            from app.extensions import db
            old_plan = sub.plan
            sub.plan = "Free Trial"
            sub.expires_at = None
            sub.starts_at = now
            sub.status = "active"
            db.session.commit()
            flash(
                f"Your subscription to the '{old_plan}' plan has expired. You have been automatically transitioned to the 'Free Trial' tier.",
                "warning"
            )

        # SHUTDOWN: Inactive status
        is_inactive = sub.status == "inactive"

        if is_inactive:
            # Allow access only to plans page or logout or verification pending
            allowed_endpoints = [
                "org.browse_plans",
                "org.checkout",
                "org.process_payment",
                "org.logout",
                "main.subscription_expired",
                "org.dashboard",
                "org.profile",
            ]

            if request.endpoint not in allowed_endpoints:
                if getattr(current_user, "role", "") == "worker":
                    return redirect(url_for("main.subscription_expired"))

                # Redirect admins to dashboard to see the popup/banner
                flash(
                    "Your subscription is completed/inactive. Please renew to continue services.",
                    "warning",
                )
                return redirect(url_for("org.dashboard"))

        return f(*args, **kwargs)

    return decorated
