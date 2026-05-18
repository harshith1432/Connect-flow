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
            return redirect(url_for("super_admin.login"))  # Updated to the new blueprint name later
        return f(*args, **kwargs)

    return decorated


def org_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # Organization users use OrganizationUser model and must have organization_id
        if not hasattr(current_user, "organization_id"):
            flash("Access denied: organization users only", "danger")
            return redirect(url_for("org.login"))
        return f(*args, **kwargs)

    return decorated


def verified_org_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        # Organization users use OrganizationUser model and must have organization_id
        if not hasattr(current_user, "organization_id"):
            flash("Access denied: organization users only", "danger")
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
                "tenant_admin.browse_plans",
                "tenant_admin.checkout",
                "tenant_admin.process_payment",
                "tenant_admin.logout",
            ]
            if request.endpoint not in allowed_endpoints:
                if getattr(current_user, "role", "") == "worker":
                    return redirect(url_for("main.subscription_expired"))

                flash(
                    "A subscription is required to access these features. Please choose a plan.",
                    "warning",
                )
                return redirect(url_for("tenant_admin.browse_plans"))
            return f(*args, **kwargs)

        now = datetime.utcnow()
        # SHUTDOWN: Inactive status OR Expiry + 3 days grace
        is_expired_shutdown = sub.expires_at and now > (
            sub.expires_at + timedelta(days=3)
        )
        is_inactive = sub.status == "inactive"

        if is_inactive or is_expired_shutdown:
            # Allow access only to plans page or logout or verification pending
            allowed_endpoints = [
                "tenant_admin.browse_plans",
                "tenant_admin.checkout",
                "tenant_admin.process_payment",
                "tenant_admin.logout",
                "main.subscription_expired",
                "tenant_admin.dashboard",
                "tenant_admin.profile",
            ]

            if request.endpoint not in allowed_endpoints:
                if getattr(current_user, "role", "") == "worker":
                    return redirect(url_for("main.subscription_expired"))

                # Redirect admins to dashboard to see the popup/banner
                flash(
                    "Your subscription is completed/inactive. Please renew to continue services.",
                    "warning",
                )
                return redirect(url_for("tenant_admin.dashboard"))

        # ALERT: If expired but within grace (3, 2, or 1 day remaining/past)
        if (
            sub.expires_at
            and now > sub.expires_at
            and not is_inactive
            and not is_expired_shutdown
        ):
            days_past = (now - sub.expires_at).days
            days_left = 3 - days_past
            flash(
                f"Your subscription has expired! You are in a grace period. {days_left} day(s) remaining before service interruption.",
                "warning",
            )

        return f(*args, **kwargs)

    return decorated
