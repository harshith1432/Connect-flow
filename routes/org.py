from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models.models import OrganizationUser, Module, ModuleField, ModuleRecord, Script, Campaign, CommunicationNumber, Contact, Plan, ChangeRequest, Organization, Subscription, DeliveryLog
from models import db
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
from utils.decorators import org_required, verified_org_required, active_subscription_required

org_bp = Blueprint('org', __name__, template_folder='../templates')


@org_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        selected_org_id = request.form.get('organization_id')
        
        # Find all admin users with this email
        matching_users = OrganizationUser.query.filter_by(email=email, role='org_admin').all()
        
        # Filter by valid password
        valid_users = [u for u in matching_users if u.check_password(password)]
        
        if not valid_users:
            flash('Invalid credentials', 'danger')
            return render_template('auth/org_login.html')
            
        # If specific org selected (from selection page)
        if selected_org_id:
            user = OrganizationUser.query.filter_by(email=email, organization_id=selected_org_id).first()
            if user and user.check_password(password):
                # Check organization status
                org_status = user.organization.status
                if org_status == 'pending':
                    return render_template('auth/access_denied.html', 
                                         status='pending', 
                                         org_name=user.organization.name)
                elif org_status == 'rejected':
                    return render_template('auth/access_denied.html', 
                                         status='rejected', 
                                         org_name=user.organization.name,
                                         reason=user.organization.description)
                elif org_status == 'suspended':
                    flash('Your organization has been suspended. Please contact platform admin.', 'danger')
                    return render_template('auth/org_login.html')
                
                login_user(user)
                return redirect(url_for('org.dashboard'))
            
        # If only one valid user, log in immediately (but check status first)
        if len(valid_users) == 1:
            user = valid_users[0]
            org_status = user.organization.status
            
            if org_status == 'pending':
                return render_template('auth/access_denied.html', 
                                     status='pending', 
                                     org_name=user.organization.name)
            elif org_status == 'rejected':
                return render_template('auth/access_denied.html', 
                                     status='rejected', 
                                     org_name=user.organization.name,
                                     reason=user.organization.description)
            elif org_status == 'suspended':
                flash('Your organization has been suspended. Please contact platform admin.', 'danger')
                return render_template('auth/org_login.html')
            
            login_user(user)
            return redirect(url_for('org.dashboard'))
            
        # Multiple orgs found, show selection page
        return render_template('auth/select_org.html', matching_users=valid_users, email=email, password=password)
        
    return render_template('auth/org_login.html')


@org_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        new_password = request.form.get('new_password')
        
        # Check if user exists as an admin for ANY organization
        user = OrganizationUser.query.filter_by(email=email, role='org_admin').first()
        if not user:
            flash('No administrator account found with this email address.', 'danger')
            return render_template('auth/forgot_password.html')
            
        # Hash the new password before storing it as a pending change
        # User requested admin approval, so we store the hash in ChangeRequest
        pw_hash = generate_password_hash(new_password)
        
        # Create Change Request
        req = ChangeRequest(
            organization_id=user.organization_id,
            user_id=user.id,
            field_name='password_reset',
            old_value='[hidden]',
            new_value=pw_hash,
            status='pending'
        )
        db.session.add(req)
        
        # Create Platform Notification
        from models.models import PlatformNotification
        notif = PlatformNotification(
            organization_id=user.organization_id,
            type='info_change',
            title='Password Reset Request',
            message=f"Organization Admin ({email}) has requested a password reset. Please review and approve.",
            link=url_for('admin.pending_changes')
        )
        db.session.add(notif)
        
        db.session.commit()
        return redirect(url_for('org.forgot_password_submitted'))
        
    return render_template('auth/forgot_password.html')


@org_bp.route('/forgot-password/submitted')
def forgot_password_submitted():
    return render_template('auth/password_reset_submitted.html')


@org_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        from models.models import Organization
        
        org_name = request.form['org_name']
        email = request.form['email']
        password = request.form['password']
        
        # Only check if email exists IN THIS organization (not across all)
        # But for registration, we are creating a new org, so it will always be new.
        # However, we might want to check if they are already an admin of an org with this email.
        # The user requested to ALLOW this.
        pass
            
        # Backend Validation
        import re
        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            flash('Password must be at least 8 characters and contain both letters and numbers.', 'danger')
            return render_template('auth/register.html')
            
        # Create Org
        new_org = Organization(name=org_name, status='pending')
        db.session.add(new_org)
        db.session.flush()
        
        # Create Org Admin
        admin = OrganizationUser(
            organization_id=new_org.id,
            email=email,
            password_hash=generate_password_hash(password),
            role='org_admin'
        )
        db.session.add(admin)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('org.login'))
        
    return render_template('auth/register.html')


@org_bp.route('/dashboard')
@verified_org_required
@active_subscription_required
def dashboard():
    # Organization-scoped data with defensive checks
    if not hasattr(current_user, 'organization_id') or current_user.organization_id is None:
        # If a platform user or anonymous reached here, redirect to org login
        flash('Access denied: organization users only', 'danger')
        return redirect(url_for('org.login'))
    org_id = current_user.organization_id
    modules = Module.query.filter_by(organization_id=org_id).all()
    numbers = CommunicationNumber.query.filter((CommunicationNumber.organization_id == org_id) | (CommunicationNumber.is_platform_owned == True)).all()
    subscription = Subscription.query.filter_by(organization_id=org_id).first()
    
    # Calculate Dashboard Stats
    worker_count = OrganizationUser.query.filter_by(organization_id=org_id, role='worker').count()
    total_calls = DeliveryLog.query.join(Campaign).filter(Campaign.organization_id == org_id, DeliveryLog.channel == 'call', DeliveryLog.status == 'completed').count()
    total_messages = DeliveryLog.query.join(Campaign).filter(Campaign.organization_id == org_id, DeliveryLog.channel.in_(['whatsapp', 'whatsapp_voice']), DeliveryLog.status.in_(['sent', 'delivered', 'read'])).count()

    # Calculate Subscription Status Banners
    days_until_expiry = None
    grace_days_left = None
    if subscription and subscription.expires_at:
        now = datetime.utcnow()
        if now < subscription.expires_at:
            delta = subscription.expires_at - now
            if delta.days < 3:
                days_until_expiry = delta.days + 1 # 1-base for display
        elif now <= (subscription.expires_at + timedelta(days=3)):
            delta_grace = (subscription.expires_at + timedelta(days=3)) - now
            grace_days_left = delta_grace.days + 1

    return render_template('organization/dashboard.html', 
                          modules=modules, 
                          numbers=numbers, 
                          subscription=subscription, 
                          days_until_expiry=days_until_expiry,
                          grace_days_left=grace_days_left,
                          total_calls=total_calls, 
                          total_messages=total_messages, 
                          worker_count=worker_count)


@org_bp.route('/modules/<int:mid>')
@verified_org_required
@active_subscription_required
def module_detail(mid):
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('org.login'))
        
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('org.dashboard'))
        
    # Gather Module Stats
    groups = m.groups  # Relationship
    total_groups = len(groups)
    
    # Total Records (sum of records in all groups)
    total_records = ModuleRecord.query.filter_by(module_id=mid).count()
    
    # Campaigns
    campaigns = Campaign.query.filter_by(module_id=mid).order_by(Campaign.created_at.desc()).all()
    total_campaigns = len(campaigns)
    
    # Campaign Results Summary
    # We'll attach a 'summary' dict to each campaign object for the template to view
    for c in campaigns:
        logs = DeliveryLog.query.filter_by(campaign_id=c.id).all()
        sent = sum(1 for l in logs if l.status in ['sent', 'delivered', 'read', 'completed', 'initiated'])
        failed = sum(1 for l in logs if l.status in ['failed', 'undelivered'])
        c.summary = {'total': len(logs), 'sent': sent, 'failed': failed}

    # Enhance Groups with stats
    for g in groups:
        g.contact_count = ModuleRecord.query.filter_by(group_id=g.id).count()
        g.campaign_count = Campaign.query.filter_by(group_id=g.id).count()

    return render_template('organization/module_detail.html', module=m, total_groups=total_groups, total_records=total_records, total_campaigns=total_campaigns, campaigns=campaigns)


@org_bp.route('/workers')
@verified_org_required
def manage_workers():
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('org.login'))
    
    workers = OrganizationUser.query.filter_by(organization_id=current_user.organization_id, role='worker').all()
    subscription = Subscription.query.filter_by(organization_id=current_user.organization_id).first()
    return render_template('organization/workers.html', workers=workers, subscription=subscription)


@org_bp.route('/workers/create', methods=['GET', 'POST'])
@verified_org_required
def create_worker():
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('org.login'))
        
    if request.method == 'POST':
        # Check subscription status
        sub = Subscription.query.filter_by(organization_id=current_user.organization_id).first()
        if not sub or sub.status == 'inactive':
            flash("A subscription is required to add workers. Please purchase a plan.", "danger")
            return redirect(url_for('org.browse_plans'))
            
        email = request.form['email']
        password = request.form['password']
        
        # Check existing
        if OrganizationUser.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('org.create_worker'))
            
        worker = OrganizationUser(
            organization_id=current_user.organization_id,
            email=email,
            password_hash=generate_password_hash(password),
            role='worker'
        )
        db.session.add(worker)
        db.session.commit()
        flash('Worker created successfully', 'success')
        return redirect(url_for('org.manage_workers'))
        
    subscription = Subscription.query.filter_by(organization_id=current_user.organization_id).first()
    return render_template('organization/worker_create.html', subscription=subscription)


@org_bp.route('/workers/<int:wid>/delete', methods=['POST'])
@verified_org_required
def delete_worker(wid):
    worker = OrganizationUser.query.get_or_404(wid)
    if worker.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('org.manage_workers'))
        
    db.session.delete(worker)
    db.session.commit()
    
    flash('Worker deleted successfully', 'success')
    return redirect(url_for('org.manage_workers'))


@org_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if not hasattr(current_user, 'organization_id') or current_user.organization_id is None:
        flash('Organization access required', 'danger')
        return redirect(url_for('main.index'))
    
    org = current_user.organization
    pending_changes = ChangeRequest.query.filter_by(organization_id=org.id, status='pending').all()
    pending_fields = [cr.field_name for cr in pending_changes]
    
    if request.method == 'POST':
        # Handles updates
        new_name = request.form.get('name')
        new_email = request.form.get('email')
        new_description = request.form.get('description')
        
        # Non-sensitive: Update immediately
        org.description = new_description
        org.org_type = request.form.get('org_type')
        org.industry = request.form.get('industry')
        org.country = request.form.get('country')
        org.office_address = request.form.get('office_address')
        org.language_preference = request.form.get('language_preference')
        org.support_email = request.form.get('support_email')
        
        # Handle Logo Upload
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            filename = secure_filename(f"{org.id}_{logo_file.filename}")
            upload_path = os.path.join('static', 'uploads', 'logos', filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            logo_file.save(upload_path)
            org.logo_url = f"uploads/logos/{filename}"
        elif 'logo_url' in request.form:
            org.logo_url = request.form.get('logo_url')
        
        # Sensitive: Create ChangeRequest
        if new_name and new_name != org.name:
            if 'org_name' not in pending_fields:
                req = ChangeRequest(
                    organization_id=org.id,
                    field_name='org_name',
                    old_value=org.name,
                    new_value=new_name
                )
                db.session.add(req)
                flash('Organization name change requested and pending approval', 'info')
        
        if new_email and new_email != current_user.email:
            if 'admin_email' not in pending_fields:
                req = ChangeRequest(
                    user_id=current_user.id,
                    organization_id=org.id,
                    field_name='admin_email',
                    old_value=current_user.email,
                    new_value=new_email
                )
                db.session.add(req)
                flash('Email change requested and pending approval', 'info')

        db.session.commit()
        flash('Profile updated successfully', 'success')
        return redirect(url_for('org.profile'))

    org = current_user.organization
    subscription = Subscription.query.filter_by(organization_id=org.id).first()
    return render_template('organization/profile.html', org=org, pending_fields=pending_fields, subscription=subscription)


@org_bp.route('/communication', methods=['GET', 'POST'])
@verified_org_required
@active_subscription_required
def communication_settings():
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('org.login'))
        
    org = current_user.organization
    numbers = CommunicationNumber.query.filter((CommunicationNumber.organization_id == org.id) | (CommunicationNumber.is_platform_owned == True)).all()
    
    # Check for pending requests
    pending_request = ChangeRequest.query.filter_by(organization_id=org.id, field_name='number_request', status='pending').first()
    
    if request.method == 'POST':
        req_type = request.form.get('type') # voice, whatsapp, or indian_voice
        
        if pending_request:
            flash('You already have a pending number request.', 'warning')
        else:
            req = ChangeRequest(
                user_id=current_user.id,
                organization_id=org.id,
                field_name='number_request',
                old_value=None,
                new_value=req_type # 'voice', 'whatsapp', or 'indian_voice'
            )
            db.session.add(req)
            db.session.commit()
            
            # Notify Platform Admin
            try:
                from services.notification_service import create_notification
                create_notification(
                    org_id=org.id,
                    type='number_request',
                    title='New Number Request',
                    message=f"{org.name} has requested a {req_type.title()} number.",
                    link=url_for('admin.org_detail', org_id=org.id)
                )
            except Exception as e:
                print(f"Failed to send notification: {e}")
                
            flash('Number request sent to platform admin.', 'success')
            return redirect(url_for('org.communication_settings'))
            
    return render_template('organization/communication_settings.html', org=org, numbers=numbers, pending_request=pending_request)


@org_bp.route('/communication/toggle/<int:nid>', methods=['POST'])
@verified_org_required
@active_subscription_required
def toggle_number(nid):
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('org.login'))
        
    num = CommunicationNumber.query.get_or_404(nid)
    # Ensure ownership or platform access
    if num.organization_id != current_user.organization_id and not num.is_platform_owned:
         flash('Access denied', 'danger')
         return redirect(url_for('org.communication_settings'))
         
    # Handle Platform Number Toggling (Affects Org Preference Granularly)
    if num.is_platform_owned:
        org = Organization.query.get(current_user.organization_id)
        
        is_whatsapp = num.channel_type == 'whatsapp'
        if is_whatsapp:
            org.allow_default_whatsapp = not org.allow_default_whatsapp
            status = "enabled" if org.allow_default_whatsapp else "disabled"
            flash(f'Default WhatsApp usage {status}', 'success')
        else:
            org.allow_default_voice = not org.allow_default_voice
            status = "enabled" if org.allow_default_voice else "disabled"
            flash(f'Default Voice usage {status}', 'success')
            
        db.session.commit()
        return redirect(url_for('org.communication_settings'))

    # Handle Custom Number Toggling
    num.active = not num.active
    db.session.commit()
    
    status = "enabled" if num.active else "disabled"
    flash(f'Number {num.number} {status}', 'success')
    return redirect(url_for('org.communication_settings'))


@org_bp.route('/communication/delete/<int:nid>', methods=['POST'])
@verified_org_required
@active_subscription_required
def delete_number(nid):
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('org.login'))
        
    num = CommunicationNumber.query.get_or_404(nid)
    
    # Security check: Only allow deleting custom numbers owned by this organization
    if num.is_platform_owned:
        flash('Cannot delete platform default numbers', 'danger')
        return redirect(url_for('org.communication_settings'))
        
    if num.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('org.communication_settings'))
    
    # Delete the number
    number_display = num.number
    db.session.delete(num)
    db.session.commit()
    
    flash(f'Number {number_display} deleted successfully', 'success')
    return redirect(url_for('org.communication_settings'))


@org_bp.route('/plans')
@login_required
def browse_plans():
    plans = Plan.query.filter_by(is_active=True).all()
    return render_template('organization/plans.html', plans=plans)


@org_bp.route('/checkout/<int:plan_id>')
@login_required
def checkout(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    org = current_user.organization
    return render_template('organization/checkout.html', plan=plan, org=org)


@org_bp.route('/payment/process', methods=['POST'])
@login_required
def process_payment():
    plan_id = request.form.get('plan_id')
    plan = Plan.query.get_or_404(plan_id)
    org = current_user.organization
    
    # Simulate payment processing logic here
    # In a real app, you'd call Stripe/Razorpay/etc.
    
    # Update Subscription
    sub = Subscription.query.filter_by(organization_id=org.id).first()
    if not sub:
        sub = Subscription(organization_id=org.id)
        db.session.add(sub)
    
    sub.plan = plan.name
    sub.status = 'active'
    sub.billing_interval = plan.billing_interval
    sub.starts_at = datetime.utcnow()
    
    # Calculate expiry
    if plan.billing_interval == 'yearly':
        sub.expires_at = sub.starts_at + timedelta(days=365)
    else:
        sub.expires_at = sub.starts_at + timedelta(days=30)
        
    # Record Payment for Revenue Dashboard
    from models.models import Payment
    payment = Payment(
        organization_id=org.id,
        amount=plan.price,
        status='completed',
        meta={'plan_name': plan.name, 'method': request.form.get('paymentMethod')}
    )
    db.session.add(payment)
    
    db.session.commit()
    
    flash(f'Successfully subscribed to {plan.name} plan!', 'success')
    return redirect(url_for('org.profile'))


@org_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))
