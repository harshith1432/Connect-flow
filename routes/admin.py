from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user
from models.models import PlatformAdmin, Organization, CommunicationNumber, Subscription, Payment, Plan, PaymentMethod, ChangeRequest, OrganizationUser
from models import db
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from utils.decorators import platform_required
from flask import request
from config import Config


admin_bp = Blueprint('admin', __name__, template_folder='../templates')


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        # Check security setting for default admin
        from models.models import PlatformSecurity
        sec_settings = PlatformSecurity.get_settings()
        
        # If trying to login as default admin, check if it's enabled
        if email == Config.DEFAULT_ADMIN_EMAIL:
            if not sec_settings.default_admin_enabled:
                flash('Default administrative access is currently disabled.', 'danger')
                return render_template('auth/platform_login.html')

        admin = PlatformAdmin.query.filter_by(email=email).first()
        if admin and admin.check_password(password):
            login_user(admin)
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('auth/platform_login.html')


@admin_bp.route('/')
@platform_required
def dashboard():
    # Platform owner only
    orgs = Organization.query.all()
    numbers = CommunicationNumber.query.filter_by(is_platform_owned=False, approved=False).all()
    
    # System Overview Stats
    total_orgs = len(orgs)
    
    # Calculate revenue (completed payments)
    total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == 'completed').scalar()
    if total_revenue is None:
        total_revenue = 0.0
        
    # Active Subscriptions
    active_subs = Subscription.query.filter_by(status='active').count()
    
    # NEW: Approved organizations without active plans
    # We find orgs with status='active' whose IDs are not in Subscription table with status='active'
    subbed_org_ids = [s.organization_id for s in Subscription.query.filter_by(status='active').all()]
    pending_subscription_orgs = Organization.query.filter(
        Organization.status == 'active',
        ~Organization.id.in_(subbed_org_ids)
    ).all()
    
    # Recent Payments
    recent_payments = Payment.query.order_by(Payment.id.desc()).limit(4).all()
    
    # Notifications
    from services.notification_service import get_recent_notifications, get_unread_count
    notifications = get_recent_notifications(10)
    unread_notifs = get_unread_count()
    
    return render_template('platform/dashboard.html', 
                           orgs=orgs, 
                           numbers=numbers,
                           total_orgs=total_orgs,
                           total_revenue=total_revenue,
                           active_subs=active_subs,
                           pending_subscription_orgs=pending_subscription_orgs,
                           recent_payments=recent_payments,
                           notifications=notifications,
                           unread_notifs=unread_notifs)


@admin_bp.route('/notifications')
@platform_required
def notifications():
    from services.notification_service import get_recent_notifications, get_unread_count
    # Fetch more for the full page
    all_notifs = get_recent_notifications(50)
    # Mark all as read logic could go here, or handled via AJAX. 
    # For now, let's just show them.
    return render_template('platform/notifications.html', notifications=all_notifs)


@admin_bp.route('/orgs/<int:org_id>')
@platform_required
def view_org_detail(org_id):
    """
    Detailed view for an organization showing registration profile
    and live operational metrics.
    """
    from models.models import OrganizationUser, DeliveryLog, Campaign
    
    org = Organization.query.get_or_404(org_id)
    subscription = Subscription.query.filter_by(organization_id=org_id).first()
    
    # 1. Registration & Profile Data (already in 'org' object)
    primary_admin = OrganizationUser.query.filter_by(
        organization_id=org_id, 
        role='org_admin'
    ).first()
    
    # 2. Worker Count
    # Assuming all users in organization_users are 'workers' except the primary admin
    worker_count = OrganizationUser.query.filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.role != 'org_admin'
    ).count()
    
    # 3. Communication Stats
    # Aggregate from DeliveryLog via Campaigns
    org_campaign_ids = [c.id for c in Campaign.query.filter_by(organization_id=org_id).all()]
    
    msg_sent = 0
    calls_made = 0
    
    if org_campaign_ids:
        msg_sent = DeliveryLog.query.filter(
            DeliveryLog.campaign_id.in_(org_campaign_ids),
            DeliveryLog.channel.in_(['whatsapp_text', 'whatsapp_voice'])
        ).count()
        
        calls_made = DeliveryLog.query.filter(
            DeliveryLog.campaign_id.in_(org_campaign_ids),
            DeliveryLog.channel == 'call'
        ).count()
    
    # 4. Subscription & Billing
    subscription = Subscription.query.filter_by(organization_id=org_id).first()
    payments = Payment.query.filter_by(organization_id=org_id).order_by(Payment.id.desc()).all()
    
    # 5. Pending Number Requests
    pending_request = ChangeRequest.query.filter_by(organization_id=org_id, field_name='number_request', status='pending').first()
    
    return render_template('platform/org_detail.html',
                           org=org,
                           admin=primary_admin,
                           worker_count=worker_count,
                           msg_sent=msg_sent,
                           calls_made=calls_made,
                           subscription=subscription,
                           payments=payments,
                           pending_request=pending_request)



@admin_bp.route('/orgs/<int:org_id>/approve', methods=['POST'])
@platform_required
def approve_org(org_id):
    from models.models import PlatformNotification
    org = Organization.query.get_or_404(org_id)
    org.status = 'active'
    org.is_verified = True
    
    # Mark related notifications as read
    PlatformNotification.query.filter_by(
        organization_id=org_id,
        type='new_organization',
        is_read=False
    ).update({'is_read': True})
    
    db.session.commit()
    flash(f'Organization {org.name} has been approved and activated.', 'success')
    return redirect(url_for('admin.pending_changes'))


@admin_bp.route('/orgs/<int:org_id>/reject', methods=['POST'])
@platform_required
def reject_org(org_id):
    from models.models import PlatformNotification
    org = Organization.query.get_or_404(org_id)
    reason = request.form.get('reason', '')
    
    org.status = 'rejected'
    org.is_verified = False
    
    # Store rejection reason in description field
    if reason:
        org.description = f"Rejected: {reason}"
    
    # Mark related notifications as read
    PlatformNotification.query.filter_by(
        organization_id=org_id,
        type='new_organization',
        is_read=False
    ).update({'is_read': True})
    
    db.session.commit()
    flash(f'Organization {org.name} has been rejected.', 'warning')
    return redirect(url_for('admin.pending_changes'))


@admin_bp.route('/orgs/<int:org_id>/suspend', methods=['POST'])
@platform_required
def suspend_org(org_id):
    org = Organization.query.get_or_404(org_id)
    org.status = 'suspended'
    org.is_verified = False
    db.session.commit()
    flash(f'Organization {org.name} has been suspended.', 'warning')
    return redirect(url_for('admin.view_org_detail', org_id=org_id))


@admin_bp.route('/orgs/<int:org_id>/delete', methods=['POST'])
@platform_required
def delete_org(org_id):
    from models.models import Campaign, Script, Contact, ContactGroup, Module, ChangeRequest, PlatformNotification
    
    org = Organization.query.get_or_404(org_id)
    org_name = org.name
    
    try:
        # Delete all associated data in correct order (respecting foreign keys)
        # Note: Many models have CASCADE delete, so they'll be auto-deleted
        # We only need to manually delete models with organization_id
        
        # 1. Delete campaigns (this will cascade delete CampaignTarget and DeliveryLog)
        Campaign.query.filter_by(organization_id=org_id).delete()
        
        # 2. Delete scripts
        Script.query.filter_by(organization_id=org_id).delete()
        
        # 3. Delete contact groups (this will cascade delete ContactGroupMap)
        ContactGroup.query.filter_by(organization_id=org_id).delete()
        
        # 4. Delete contacts
        Contact.query.filter_by(organization_id=org_id).delete()
        
        # 5. Delete modules (this will cascade delete ModuleField, ModuleRecord, ModuleRecordValue, ModuleGroup)
        Module.query.filter_by(organization_id=org_id).delete()
        
        # 6. Delete subscriptions
        Subscription.query.filter_by(organization_id=org_id).delete()
        
        # 7. Delete payments
        Payment.query.filter_by(organization_id=org_id).delete()
        
        # 8. Delete communication numbers
        CommunicationNumber.query.filter_by(organization_id=org_id).delete()
        
        # 9. Delete change requests
        ChangeRequest.query.filter_by(organization_id=org_id).delete()
        
        # 10. Delete platform notifications
        PlatformNotification.query.filter_by(organization_id=org_id).delete()
        
        # 11. Delete organization users
        OrganizationUser.query.filter_by(organization_id=org_id).delete()
        
        # 12. Finally, delete the organization itself
        db.session.delete(org)
        db.session.commit()
        
        flash(f'Organization "{org_name}" and all associated data have been permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting organization: {str(e)}', 'danger')
    
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/orgs/<int:org_id>/toggle_subscription', methods=['POST'])
@platform_required
def toggle_subscription_status(org_id):
    sub = Subscription.query.filter_by(organization_id=org_id).first()
    if not sub:
        sub = Subscription(organization_id=org_id, status='active')
        db.session.add(sub)
    
    # Toggle status
    sub.status = 'inactive' if sub.status == 'active' else 'active'
    db.session.commit()
    
    flash(f"Subscription status for organization updated to {sub.status.upper()}", 'success')
    flash(f"Subscription status for organization updated to {sub.status.upper()}", 'success')
    return redirect(url_for('admin.view_org_detail', org_id=org_id))


@admin_bp.route('/orgs/<int:org_id>/configure_twilio', methods=['POST'])
@platform_required
def configure_twilio(org_id):
    org = Organization.query.get_or_404(org_id)
    
    # Get form data
    voice_sid = request.form.get('voice_sid')
    voice_token = request.form.get('voice_token')
    voice_number = request.form.get('voice_number')
    
    wa_sid = request.form.get('wa_sid')
    wa_token = request.form.get('wa_token')
    wa_number = request.form.get('wa_number')
    
    # Exotel Config
    exotel_api_key = request.form.get('exotel_api_key')
    exotel_api_token = request.form.get('exotel_api_token')
    exotel_subdomain = request.form.get('exotel_subdomain')
    exotel_number = request.form.get('exotel_number')
    
    # Update Config
    config = org.twilio_config or {}
    
    if voice_sid and voice_token and voice_number:
        config['voice'] = {
            'sid': voice_sid,
            'token': voice_token,
            'number': voice_number
        }
        # Clear pending voice request
        req = ChangeRequest.query.filter_by(organization_id=org_id, field_name='number_request', status='pending', new_value='voice').first()
        if req:
            req.status = 'approved'
        
        # Add to CommunicationNumber for visibility
        from models.models import CommunicationNumber
        exists = CommunicationNumber.query.filter_by(organization_id=org_id, number=voice_number).first()
        if not exists:
            cn = CommunicationNumber(organization_id=org_id, number=voice_number, channel_type='voice', approved=True, active=True, is_platform_owned=False)
            db.session.add(cn)

    if wa_sid and wa_token and wa_number:
        config['whatsapp'] = {
            'sid': wa_sid,
            'token': wa_token,
            'number': wa_number
        }
        # Clear pending whatsapp request
        req = ChangeRequest.query.filter_by(organization_id=org_id, field_name='number_request', status='pending', new_value='whatsapp').first()
        if req:
            req.status = 'approved'
            
        # Add to CommunicationNumber
        from models.models import CommunicationNumber
        exists = CommunicationNumber.query.filter_by(organization_id=org_id, number=wa_number).first()
        if not exists:
            cn = CommunicationNumber(organization_id=org_id, number=wa_number, channel_type='whatsapp', approved=True, active=True, is_platform_owned=False)
            db.session.add(cn)

    if exotel_api_key and exotel_api_token and exotel_number:
        config['exotel'] = {
            'api_key': exotel_api_key,
            'api_token': exotel_api_token,
            'subdomain': exotel_subdomain,
            'number': exotel_number
        }
        # Clear pending indian_voice request
        req = ChangeRequest.query.filter_by(organization_id=org_id, field_name='number_request', status='pending', new_value='indian_voice').first()
        if req:
            req.status = 'approved'
            
        # Add to CommunicationNumber
        from models.models import CommunicationNumber
        exists = CommunicationNumber.query.filter_by(organization_id=org_id, number=exotel_number).first()
        if not exists:
            cn = CommunicationNumber(organization_id=org_id, number=exotel_number, channel_type='indian_voice', approved=True, active=True, is_platform_owned=False)
            db.session.add(cn)

    # MyOperator Config
    myoperator_token = request.form.get('myoperator_token')
    myoperator_number = request.form.get('myoperator_number')
    myoperator_wa_number = request.form.get('myoperator_wa_number')
    myoperator_wa_key = request.form.get('myoperator_wa_key')
    myoperator_company_id = request.form.get('myoperator_company_id')

    myoperator_secret_key = request.form.get('myoperator_secret_key')
    myoperator_x_api_key = request.form.get('myoperator_x_api_key')
    myoperator_ivr_id = request.form.get('myoperator_ivr_id')

    if myoperator_token or myoperator_wa_key or myoperator_x_api_key:
        config['myoperator'] = {
            'token': myoperator_token,
            'number': myoperator_number,
            'wa_number': myoperator_wa_number,
            'wa_key': myoperator_wa_key,
            'company_id': myoperator_company_id,
            'secret_key': myoperator_secret_key,
            'x_api_key': myoperator_x_api_key,
            'ivr_id': myoperator_ivr_id
        }
        # Clear pending myoperator requests
        pending_reqs = ChangeRequest.query.filter(
            ChangeRequest.organization_id == org_id,
            ChangeRequest.field_name == 'number_request',
            ChangeRequest.status == 'pending',
            ChangeRequest.new_value.in_(['myoperator_voice', 'myoperator_whatsapp'])
        ).all()
        for req in pending_reqs:
            req.status = 'approved'
            
        # Add to CommunicationNumber
        from models.models import CommunicationNumber
        # Add Voice version
        if myoperator_number:
            cn_voice = CommunicationNumber.query.filter_by(organization_id=org_id, number=myoperator_number, channel_type='myoperator_voice').first()
            if not cn_voice:
                cn_v = CommunicationNumber(organization_id=org_id, number=myoperator_number, channel_type='myoperator_voice', approved=True, active=True, is_platform_owned=False)
                db.session.add(cn_v)

        # Add WhatsApp version (use wa_number if exists, else fallback to voice number)
        wa_num = myoperator_wa_number or myoperator_number
        if wa_num:
            cn_wa = CommunicationNumber.query.filter_by(organization_id=org_id, number=wa_num, channel_type='myoperator_whatsapp').first()
            if not cn_wa:
                cn_w = CommunicationNumber(organization_id=org_id, number=wa_num, channel_type='myoperator_whatsapp', approved=True, active=True, is_platform_owned=False)
                db.session.add(cn_w)
            
    # Force update JSON column
    org.twilio_config = config
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(org, "twilio_config")
    
    db.session.commit()
    flash('Twilio configuration updated successfully', 'success')
    return redirect(url_for('admin.view_org_detail', org_id=org_id))


@admin_bp.route('/numbers/approve/<int:nid>', methods=['POST'])
@platform_required
def approve_number(nid):
    num = CommunicationNumber.query.get_or_404(nid)
    num.approved = True
    db.session.commit()
    flash('Number approved', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/settings/plans', methods=['GET', 'POST'])
@platform_required
def manage_plans():
    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price')
        billing_interval = request.form.get('billing_interval', 'monthly')
        description = request.form.get('description')
        features_str = request.form.get('features') # Comma separated
        features = [f.strip() for f in features_str.split(',')] if features_str else []
        
        plan_id = request.form.get('plan_id')
        if plan_id:
            plan = Plan.query.get(plan_id)
            if plan:
                plan.name = name
                plan.price = price
                plan.billing_interval = billing_interval
                plan.description = description
                plan.features = features
                flash(f'Plan {name} updated', 'success')
        else:
            plan = Plan(
                name=name,
                price=price,
                billing_interval=billing_interval,
                description=description,
                features=features
            )
            db.session.add(plan)
            flash(f'Plan {name} created successfully', 'success')
            
        db.session.commit()
        return redirect(url_for('admin.manage_plans'))
        
    plans = Plan.query.order_by(Plan.price.asc()).all()
    return render_template('platform/settings_plans.html', plans=plans)


@admin_bp.route('/settings/plans/delete/<int:plan_id>', methods=['POST'])
@platform_required
def delete_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    db.session.delete(plan)
    db.session.commit()
    flash(f'Plan {plan.name} deleted', 'info')
    return redirect(url_for('admin.manage_plans'))


@admin_bp.route('/settings/payments', methods=['GET', 'POST'])
@platform_required
def manage_payments():
    if request.method == 'POST':
        name = request.form.get('name')
        method_type = request.form.get('type', 'manual') # gateway/manual
        instructions = request.form.get('instructions')
        
        method_id = request.form.get('method_id')
        if method_id:
            pm = PaymentMethod.query.get(method_id)
            if pm:
                pm.name = name
                pm.type = method_type
                pm.instructions = instructions
                flash(f'Payment method {name} updated', 'success')
        else:
            pm = PaymentMethod(
                name=name,
                type=method_type,
                instructions=instructions
            )
            db.session.add(pm)
            flash(f'Payment method {name} added', 'success')
            
        db.session.commit()
        return redirect(url_for('admin.manage_payments'))
        
    methods = PaymentMethod.query.all()
    return render_template('platform/settings_payments.html', methods=methods)


@admin_bp.route('/settings/payments/delete/<int:method_id>', methods=['POST'])
@platform_required
def delete_payment_method(method_id):
    pm = PaymentMethod.query.get_or_404(method_id)
    db.session.delete(pm)
    db.session.commit()
    flash(f'Payment method {pm.name} removed', 'info')
    return redirect(url_for('admin.manage_payments'))


@admin_bp.route('/changes')
@platform_required
def pending_changes():
    requests = ChangeRequest.query.filter_by(status='pending').order_by(ChangeRequest.created_at.desc()).all()
    pending_orgs = Organization.query.filter_by(status='pending').order_by(Organization.created_at.desc()).all()
    return render_template('platform/pending_changes.html', requests=requests, pending_orgs=pending_orgs)


@admin_bp.route('/changes/<int:rid>/review', methods=['POST'])
@platform_required
def review_change(rid):
    req = ChangeRequest.query.get_or_404(rid)
    action = request.form.get('action') # approve or reject
    
    if action == 'approve':
        if req.field_name == 'org_name':
            org = Organization.query.get(req.organization_id)
            if org:
                org.name = req.new_value
        elif req.field_name == 'admin_email':
            user = OrganizationUser.query.get(req.user_id)
            if user:
                user.email = req.new_value
        elif req.field_name == 'password_reset':
            user = OrganizationUser.query.get(req.user_id)
            if user:
                user.password_hash = req.new_value
        
        req.status = 'approved'
        flash('Change request approved and applied', 'success')
    else:
        req.status = 'rejected'
        flash('Change request rejected', 'warning')
    
    req.reviewed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('admin.pending_changes'))


@admin_bp.route('/settings/admins', methods=['GET', 'POST'])
@platform_required
def manage_admins():
    from models.models import PlatformSecurity
    sec = PlatformSecurity.get_settings()
    
    if request.method == 'POST':
        # Toggle default admin
        sec.default_admin_enabled = 'default_admin_enabled' in request.form
        db.session.commit()
        flash('Platform security settings updated', 'success')
        return redirect(url_for('admin.manage_admins'))
        
    admins = PlatformAdmin.query.all()
    return render_template('platform/settings_admins.html', admins=admins, security=sec, default_email=Config.DEFAULT_ADMIN_EMAIL)


@admin_bp.route('/settings/admins/add', methods=['POST'])
@platform_required
def add_admin():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        flash('Email and password are required', 'danger')
        return redirect(url_for('admin.manage_admins'))
        
    exists = PlatformAdmin.query.filter_by(email=email).first()
    if exists:
        flash('An admin with this email already exists', 'danger')
        return redirect(url_for('admin.manage_admins'))
        
    new_admin = PlatformAdmin(
        email=email,
        password_hash=generate_password_hash(password)
    )
    db.session.add(new_admin)
    db.session.commit()
    flash(f'Platform admin {email} added successfully', 'success')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/settings/admins/update/<int:aid>', methods=['POST'])
@platform_required
def update_admin(aid):
    admin = PlatformAdmin.query.get_or_404(aid)
    email = request.form.get('email')
    password = request.form.get('password')
    
    if email:
        admin.email = email
    if password:
        admin.password_hash = generate_password_hash(password)
        
    db.session.commit()
    flash(f'Admin {admin.email} updated', 'success')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/settings/admins/delete/<int:aid>', methods=['POST'])
@platform_required
def delete_admin(aid):
    admin = PlatformAdmin.query.get_or_404(aid)
    
    # Don't delete self
    from flask_login import current_user
    if admin.id == current_user.id:
        flash('You cannot delete your own account while logged in.', 'danger')
        return redirect(url_for('admin.manage_admins'))
        
    db.session.delete(admin)
    db.session.commit()
    flash(f'Admin {admin.email} removed', 'info')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))
