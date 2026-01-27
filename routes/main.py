from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db
from models.models import Organization, OrganizationUser
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import os
from sqlalchemy import text
from models.models import Subscription

main_bp = Blueprint('main', __name__, template_folder='templates')


@main_bp.route('/subscription-expired')
def subscription_expired():
    return render_template('main/subscription_expired.html')


@main_bp.route('/')
def index():
    # Health check: verify DB connection
    db_ok = True
    db_error = None
    try:
        db.session.execute(text('SELECT 1'))
    except Exception as e:
        db_ok = False
        db_error = str(e)
    return render_template('index.html', db_ok=db_ok, db_error=db_error)


@main_bp.route('/org/register', methods=['GET', 'POST'])
def org_register():
    if request.method == 'POST':
        # Step 1: Org Details
        org_name = request.form.get('org_name')
        org_type = request.form.get('org_type')
        industry = request.form.get('industry')
        country = request.form.get('country')
        office_address = request.form.get('office_address')

        # Step 2: Admin Details
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        designation = request.form.get('designation')
        phone = request.form.get('phone')

        # Step 3: Branding & Support
        language_preference = request.form.get('language_preference', 'English')
        support_email = request.form.get('support_email')
        support_phone = request.form.get('support_phone')

        # Basic validation
        if not all([org_name, email, password]):
            flash('Company name, Email, and Password are required.', 'danger')
            return render_template('auth/register_stepper.html'), 400

        # Validate Phone Number (10 digits)
        import re
        if phone and not re.match(r'^\d{10}$', phone):
            flash('Mobile Number must be exactly 10 digits.', 'danger')
            return render_template('auth/register_stepper.html'), 400

        # Validate Email Format
        if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('auth/register_stepper.html'), 400

        # Validate Support Contacts
        if support_phone and not re.match(r'^\d{10}$', support_phone):
            flash('Public Support Phone must be exactly 10 digits.', 'danger')
            return render_template('auth/register_stepper.html'), 400
        
        if support_email and not re.match(r"[^@]+@[^@]+\.[^@]+", support_email):
            flash('Please enter a valid support email address.', 'danger')
            return render_template('auth/register_stepper.html'), 400

        # Check if email exists
        existing_user = db.session.query(OrganizationUser).filter_by(email=email).first()
        if existing_user:
            flash('Email already registered.', 'danger')
            return render_template('auth/register_stepper.html'), 400

        # Handle Logo Upload
        logo_url = None
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            filename = secure_filename(f"{org_name}_{logo_file.filename}")
            upload_path = os.path.join('static', 'uploads', 'logos', filename)
            # Ensure directory exists (mkdir -p logic)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            logo_file.save(upload_path)
            logo_url = f"uploads/logos/{filename}"

        # 1. Create Organization (Pending)
        org = Organization(
            name=org_name,
            org_type=org_type,
            industry=industry,
            country=country,
            office_address=office_address,
            logo_url=logo_url,
            language_preference=language_preference,
            support_email=support_email,
            support_phone=support_phone,
            status='pending' # Explicitly set to pending
        )
        db.session.add(org)
        db.session.flush()

        # 2. Create Subscription (Trial)
        sub = Subscription(
            organization_id=org.id,
            plan='Trial',
            status='active'
        )
        db.session.add(sub)

        # 3. Create Admin User
        user = OrganizationUser(
            organization_id=org.id,
            email=email,
            password_hash=generate_password_hash(password),
            role='org_admin',
            designation=designation,
            phone=phone
        )
        db.session.add(user)
        
        # 4. Create Platform Notification for Admin
        from models.models import PlatformNotification
        notification = PlatformNotification(
            organization_id=org.id,
            type='new_organization',
            message=f'New organization "{org_name}" has registered and is awaiting approval',
            is_read=False
        )
        db.session.add(notification)
        
        db.session.commit()

        return redirect(url_for('main.registration_success'))

    return render_template('auth/register_stepper.html')


@main_bp.route('/org/registration-success')
def registration_success():
    return render_template('auth/registration_success.html')


@main_bp.route('/verification-pending')
def verification_pending():
    return render_template('auth/verification_pending.html')


# org_login and worker_login removed to avoid conflict with org_bp and worker_bp


# Legal Document Routes
@main_bp.route('/legal/terms-of-service')
def terms_of_service():
    return render_template('legal/terms_of_service.html')


@main_bp.route('/legal/privacy-policy')
def privacy_policy():
    return render_template('legal/privacy_policy.html')


@main_bp.route('/legal/dpa')
def dpa():
    return render_template('legal/dpa.html')
