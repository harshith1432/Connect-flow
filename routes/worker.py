from datetime import datetime, timedelta
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models.models import OrganizationUser, Module, ModuleField, ModuleRecord, ModuleRecordValue, Contact, Script, Campaign, CampaignTarget, DeliveryLog, ModuleGroup, Organization
from models import db
from utils.decorators import worker_required, active_subscription_required
import os
import threading
import time
from flask import current_app

logger = logging.getLogger(__name__)

worker_bp = Blueprint('worker', __name__, template_folder='../templates')


def delete_transient_file(file_path, delay=120):
    """Delete a file after a specific delay in seconds."""
    def _delete():
        time.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"DEBUG: Transient voice note {file_path} deleted after {delay}s.")
        except Exception as e:
            print(f"DEBUG: Error auto-deleting transient file {file_path}: {e}")
    threading.Thread(target=_delete, daemon=True).start()


@worker_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        selected_org_id = request.form.get('organization_id')
        
        # Matching users with valid password
        matching_users = OrganizationUser.query.filter_by(email=email).all()
        valid_users = [u for u in matching_users if u.check_password(password)]
        
        if not valid_users:
            flash('Invalid credentials', 'danger')
            return render_template('auth/worker_login.html')
            
        if selected_org_id:
            user = OrganizationUser.query.filter_by(email=email, organization_id=selected_org_id).first()
            if user and user.check_password(password):
                # Check subscription status
                from models.models import Subscription
                sub = Subscription.query.filter_by(organization_id=user.organization_id).first()
                if not sub or sub.status == 'inactive' or (sub.expires_at and datetime.utcnow() > sub.expires_at + timedelta(days=3)):
                    flash('Organization services are suspended or a subscription is required. Please contact your administrator.', 'danger')
                    return render_template('auth/worker_login.html')
                    
                login_user(user)
                return redirect(url_for('worker.dashboard'))
                
        if len(valid_users) == 1:
            user = valid_users[0]
            # Check subscription status
            from models.models import Subscription
            sub = Subscription.query.filter_by(organization_id=user.organization_id).first()
            if not sub or sub.status == 'inactive' or (sub.expires_at and datetime.utcnow() > sub.expires_at + timedelta(days=3)):
                flash('Organization services are suspended or a subscription is required. Please contact your administrator.', 'danger')
                return render_template('auth/worker_login.html')
                
            login_user(user)
            return redirect(url_for('worker.dashboard'))
            
        # If multiple valid accounts, show selection (reusing the auth/select_org template)
        return render_template('auth/select_org.html', matching_users=valid_users, email=email, password=password)
        
    return render_template('auth/worker_login.html')


@worker_bp.route('/dashboard')
@worker_required
@active_subscription_required
def dashboard():
    # show worker-level views inside their organization
    if not hasattr(current_user, 'organization_id') or getattr(current_user, 'role', '') != 'worker':
        flash('Access denied: worker only', 'danger')
        return redirect(url_for('worker.login'))
    org_id = current_user.organization_id
    modules = Module.query.filter_by(organization_id=org_id).all()
    return render_template('worker/dashboard.html', modules=modules)


@worker_bp.route('/modules/create', methods=['GET', 'POST'])
@worker_required
@active_subscription_required
def create_module():
    if not hasattr(current_user, 'organization_id'):
        flash('Access denied', 'danger')
        return redirect(url_for('worker.login'))
        
    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description')
        
        m = Module(
            organization_id=current_user.organization_id,
            name=name,
            description=description,
            status='active'
        )
        db.session.add(m)
        db.session.commit()
        flash('Module created successfully', 'success')
        return redirect(url_for('worker.dashboard'))
        
    return render_template('worker/module_create.html')


@worker_bp.route('/modules/<int:mid>/groups')
@worker_required
@active_subscription_required
def manage_groups(mid):
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    return render_template('worker/groups.html', module=m)


@worker_bp.route('/modules/<int:mid>/groups/add', methods=['POST'])
@worker_required
@active_subscription_required
def add_group(mid):
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    name = request.form['name']
    g = ModuleGroup(module_id=m.id, name=name)
    db.session.add(g)
    db.session.commit()
    flash('Group created successfully', 'success')
    return redirect(url_for('worker.manage_groups', mid=mid))


@worker_bp.route('/groups/<int:gid>/edit', methods=['POST'])
@worker_required
@active_subscription_required
def edit_group(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    g.name = request.form['name']
    db.session.commit()
    flash('Group updated', 'success')
    return redirect(url_for('worker.manage_groups', mid=m.id))


@worker_bp.route('/groups/<int:gid>/delete', methods=['POST'])
@worker_required
@active_subscription_required
def delete_group(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    db.session.delete(g)
    db.session.commit()
    flash('Group deleted', 'success')
    return redirect(url_for('worker.manage_groups', mid=m.id))



@worker_bp.route('/groups/<int:gid>')
@worker_required
@active_subscription_required
def group_dashboard(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    return render_template('worker/module_detail.html', module=m, group=g, fields=g.fields)


@worker_bp.route('/modules/<int:mid>')
@worker_required
@active_subscription_required
def module_detail(mid):
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    return render_template('worker/module_detail.html', module=m, group=None, fields=m.fields)


@worker_bp.route('/modules/<int:mid>/fields', methods=['POST'])
@worker_required
@active_subscription_required
def add_field(mid):
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    name = request.form['name']
    field_type = request.form['field_type']
    is_unique = request.form.get('is_unique') == 'true'
    
    meta = {}
    if field_type == 'calculated':
        meta['formula'] = request.form.get('formula')
    elif field_type == 'boolean':
        import json
        meta['logic'] = json.loads(request.form.get('logic', '{}'))
        meta['actions'] = json.loads(request.form.get('actions', '[]'))

    f = ModuleField(module_id=m.id, name=name, field_type=field_type, is_unique=is_unique, meta=meta)
    db.session.add(f)
    db.session.commit()
    flash('Field added', 'success')
    return redirect(url_for('worker.module_detail', mid=mid))


@worker_bp.route('/modules/<int:mid>/fields/<int:fid>/delete', methods=['POST'])
@worker_required
def delete_field(mid, fid):
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    f = ModuleField.query.get_or_404(fid)
    if f.module_id != m.id:
        flash('Field mismatch', 'danger')
        return redirect(url_for('worker.module_detail', mid=mid))
    
    # Delete associated values first (cascade manually just in case)
    ModuleRecordValue.query.filter_by(field_id=f.id).delete()
    db.session.delete(f)
    db.session.commit()
    
    flash('Field deleted', 'success')
    return redirect(url_for('worker.module_detail', mid=mid))


@worker_bp.route('/modules/<int:mid>/fields/<int:fid>/update', methods=['POST'])
@worker_required
def update_field(mid, fid):
    m = Module.query.get_or_404(mid)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    f = ModuleField.query.get_or_404(fid)
    if f.module_id != m.id:
        flash('Field mismatch', 'danger')
        return redirect(url_for('worker.module_detail', mid=mid))
    
    f.name = request.form['name']
    f.field_type = request.form['field_type']
    f.is_unique = request.form.get('is_unique') == 'true'
    
    if f.field_type == 'calculated':
        f.meta = f.meta or {}
        f.meta['formula'] = request.form.get('formula')
    elif f.field_type == 'boolean':
        import json
        f.meta = f.meta or {}
        f.meta['logic'] = json.loads(request.form.get('logic', '{}'))
        f.meta['actions'] = json.loads(request.form.get('actions', '[]'))
        
    db.session.commit()
    
    flash('Field updated', 'success')
    return redirect(url_for('worker.module_detail', mid=mid))


@worker_bp.route('/groups/<int:gid>/fields', methods=['POST'])
@worker_required
def add_group_field(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    name = request.form['name']
    field_type = request.form['field_type']
    is_unique = request.form.get('is_unique') == 'true'
    
    meta = {}
    if field_type == 'calculated':
        meta['formula'] = request.form.get('formula')
    elif field_type == 'boolean':
        import json
        meta['logic'] = json.loads(request.form.get('logic', '{}'))
        meta['actions'] = json.loads(request.form.get('actions', '[]'))

    f = ModuleField(module_id=m.id, group_id=g.id, name=name, field_type=field_type, is_unique=is_unique, meta=meta)
    db.session.add(f)
    db.session.commit()
    flash('Field added to group', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))


@worker_bp.route('/groups/<int:gid>/fields/<int:fid>/delete', methods=['POST'])
@worker_required
def delete_group_field(gid, fid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    f = ModuleField.query.get_or_404(fid)
    if f.group_id != g.id:
        flash('Field mismatch', 'danger')
        return redirect(url_for('worker.group_dashboard', gid=gid))
    
    ModuleRecordValue.query.filter_by(field_id=f.id).delete()
    db.session.delete(f)
    db.session.commit()
    
    flash('Field deleted', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))


@worker_bp.route('/groups/<int:gid>/fields/<int:fid>/update', methods=['POST'])
@worker_required
def update_group_field(gid, fid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    f = ModuleField.query.get_or_404(fid)
    if f.group_id != g.id:
        flash('Field mismatch', 'danger')
        return redirect(url_for('worker.group_dashboard', gid=gid))
    
    f.name = request.form['name']
    f.field_type = request.form['field_type']
    f.is_unique = request.form.get('is_unique') == 'true'

    if f.field_type == 'calculated':
        f.meta = f.meta or {}
        f.meta['formula'] = request.form.get('formula')
    elif f.field_type == 'boolean':
        import json
        f.meta = f.meta or {}
        f.meta['logic'] = json.loads(request.form.get('logic', '{}'))
        f.meta['actions'] = json.loads(request.form.get('actions', '[]'))

    db.session.commit()
    
    flash('Field updated', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))


    # Get scripts for this group
    scripts = Script.query.filter_by(group_id=gid).all()
    return render_template('worker/scripts.html', module=m, group=g, scripts=scripts)


def get_lang_code_for_generator(lang_name):
    """Map full language name to code supported by gTTS/Translator"""
    mapping = {
        'English': 'en',
        'Hindi': 'hi',
        'Kannada': 'kn',
        'Tamil': 'ta',
        'Telugu': 'te',
        'Malayalam': 'ml',
        'Marathi': 'mr'
    }
    return mapping.get(lang_name, 'en')


@worker_bp.route('/groups/<int:gid>/scripts', methods=['GET', 'POST'])
@worker_required
def scripts(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    if request.method == 'POST':
        lang = request.form['language']
        stype = request.form['type']
        content = request.form['content']
        voice_content = request.form.get('voice_content')  # Optional second field
        
        meta_data = {}
        
        # Generate Audio Preview if voice content exists (or for call types)
        # Rule: Use voice_content if present, else use content (for calls/simple text)
        tts_text = voice_content if voice_content else content
        
        if tts_text: 
            import re
            # Replace placeholders {{key}} with "key" for preview purposes
            # e.g. "Hello {{name}}" -> "Hello name"
            preview_text = re.sub(r'\{\{(.*?)\}\}', r'\1', tts_text)
            
            from voice_generator import get_voice_generator
            voice_gen = get_voice_generator()
            lang_code = get_lang_code_for_generator(lang)
            
            # For preview, we use generic generator directly
            audio_res = voice_gen.generate_generic_voice_message(preview_text.strip(), language=lang_code)
            
            if audio_res['success']:
                # Store URL relative to static
                meta_data['preview_url'] = f"audio/{audio_res['filename']}"
        
        # Twilio Content API support
        content_sid = request.form.get('content_sid')
        if content_sid:
            meta_data['content_sid'] = content_sid.strip()
            
        raw_map = request.form.get('content_variables_map')
        if raw_map:
            try:
                import json
                meta_data['content_variables_map'] = json.loads(raw_map)
            except:
                pass

        s = Script(
            module_id=m.id,
            group_id=g.id,
            language=lang,
            type=stype,
            content=content,
            voice_content=voice_content,
            meta=meta_data
        )
        db.session.add(s)
        db.session.commit()
        flash('Script created successfully', 'success')
        return redirect(url_for('worker.scripts', gid=gid))
        
    # Get scripts for this group
    scripts_list = Script.query.filter_by(group_id=gid).all()
    
    # Get module fields for placeholder buttons (Filter only current group or global fields)
    fields = ModuleField.query.filter(
        (ModuleField.module_id == m.id) & 
        ((ModuleField.group_id == None) | (ModuleField.group_id == gid))
    ).all()
    
    return render_template('worker/scripts.html', module=m, group=g, scripts=scripts_list, fields=fields)


@worker_bp.route('/scripts/<int:sid>/delete', methods=['POST'])
@worker_required
def delete_script(sid):
    s = Script.query.get_or_404(sid)
    g = ModuleGroup.query.get(s.group_id)
    m = Module.query.get(g.module_id)
    if not m or m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    # Delete associated voice note if exists
    if s.meta and 'preview_url' in s.meta:
        try:
            audio_path = os.path.join(current_app.static_folder, s.meta['preview_url'])
            if os.path.exists(audio_path):
                os.remove(audio_path)
                print(f"DEBUG: Deleted script voice note: {audio_path}")
        except Exception as e:
            print(f"DEBUG: Failed to delete script voice note: {e}")

    db.session.delete(s)
    db.session.commit()
    flash('Script deleted', 'success')

    return redirect(url_for('worker.scripts', gid=g.id))


@worker_bp.route('/scripts/<int:sid>/edit', methods=['GET', 'POST'])
@worker_required
def edit_script(sid):
    s = Script.query.get_or_404(sid)
    g = ModuleGroup.query.get(s.group_id)
    m = Module.query.get(g.module_id)
    if not m or m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    if request.method == 'POST':
        s.language = request.form['language']
        s.type = request.form['type']
        s.content = request.form['content']
        s.voice_content = request.form.get('voice_content')
        
        # Regenerate Preview
        tts_text = s.voice_content if s.voice_content else s.content
        
        # Preserve existing meta or init new
        meta_data = s.meta if s.meta else {}
        
        if tts_text:
            import re
            preview_text = re.sub(r'\{\{(.*?)\}\}', r'\1', tts_text)
            
            from voice_generator import get_voice_generator
            voice_gen = get_voice_generator()
            lang_code = get_lang_code_for_generator(s.language)
            
            audio_res = voice_gen.generate_generic_voice_message(preview_text.strip(), language=lang_code)
            if audio_res['success']:
                meta_data['preview_url'] = f"audio/{audio_res['filename']}"
            else:
                # If generation failed, keep old or log error?
                pass
        else:
            # If empty content, remove preview
            if 'preview_url' in meta_data:
                del meta_data['preview_url']
            
        s.meta = meta_data
        
        # Twilio Content API support
        new_sid = request.form.get('content_sid')
        if new_sid:
            s.meta['content_sid'] = new_sid.strip()
        elif 'content_sid' in s.meta:
            del s.meta['content_sid']
            
        raw_map = request.form.get('content_variables_map')
        if raw_map:
            try:
                import json
                s.meta['content_variables_map'] = json.loads(raw_map)
            except:
                pass
        elif 'content_variables_map' in s.meta:
            del s.meta['content_variables_map']

        db.session.commit()
        flash('Script updated successfully', 'success')
        return redirect(url_for('worker.scripts', gid=g.id))
    
    # Get module fields for placeholder buttons (Filter only current group or global fields)
    fields = ModuleField.query.filter(
        (ModuleField.module_id == m.id) & 
        ((ModuleField.group_id == None) | (ModuleField.group_id == g.id))
    ).all()
    return render_template('worker/script_edit.html', module=m, group=g, script=s, fields=fields)


@worker_bp.route('/groups/<int:gid>/campaigns', methods=['GET', 'POST'])
@worker_required
def campaigns(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    if request.method == 'POST':
        name = request.form['name']
        ctype = request.form['type']
        sid = request.form['script_id']
        sender_id = request.form.get('sender_number_id')
        
        c = Campaign(
            organization_id=m.organization_id,
            module_id=m.id,
            group_id=g.id,
            name=name,
            type=ctype,
            script_id=sid,
            sender_number_id=sender_id if sender_id else None,
            status='draft'
        )
        db.session.add(c)
        db.session.commit()
        flash('Campaign created', 'success')
        return redirect(url_for('worker.campaigns', gid=gid))
        
    campaigns = Campaign.query.filter_by(group_id=gid).order_by(Campaign.id.desc()).all()
    scripts = Script.query.filter_by(group_id=gid).all()
    
    # Fetch available numbers for this organization
    from models.models import CommunicationNumber
    numbers = CommunicationNumber.query.filter_by(organization_id=m.organization_id, active=True, approved=True).all()
    
    return render_template('worker/campaigns.html', module=m, group=g, campaigns=campaigns, scripts=scripts, numbers=numbers)


@worker_bp.route('/campaigns/<int:cid>/start', methods=['POST'])
@worker_required
def start_campaign(cid):
    c = Campaign.query.get_or_404(cid)
    # Organization check
    if c.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    # CRITICAL: Check for Disabled Communication Channels
    # If the org has opted for custom numbers but turned them ALL off, AND disabled default fallback,
    # we must BLOCK the campaign.
    from models.models import CommunicationNumber, Organization
    
    # 1. Determine required channel
    is_whatsapp = 'whatsapp' in c.type
    service_name = "WhatsApp" if is_whatsapp else "Voice Call"
    
    # 2. Check for ACTIVE custom number for this channel
    active_query = CommunicationNumber.query.filter_by(
        organization_id=c.organization_id, 
        is_platform_owned=False,
        active=True,
        approved=True
    )
    
    has_active_custom = False
    if is_whatsapp:
        has_active_custom = active_query.filter(CommunicationNumber.channel_type == 'whatsapp').count() > 0
    else:
        has_active_custom = active_query.filter(CommunicationNumber.channel_type.in_(['voice', 'indian_voice'])).count() > 0
        
    # 3. If no active custom number, check if Default Access is Allowed
    if not has_active_custom:
        org = Organization.query.get(c.organization_id)
        default_allowed = org.allow_default_whatsapp if is_whatsapp else org.allow_default_voice
        
        if not default_allowed:
             # Both Custom and Default are unavailable
             flash(f'Organization Admin has disabled {service_name} services. Campaign paused.', 'danger')
             return redirect(url_for('worker.campaigns', gid=c.group_id))

    c.status = 'running'
    db.session.commit()
    print(f"DEBUG: Starting campaign {cid}, type={c.type}")
    
    try:
        from communication.whatsapp_dispatcher import dispatch_whatsapp
        from voice_generator import get_voice_generator

        # Get Group/Records
        group = ModuleGroup.query.get(c.group_id)
        if not group:
            flash('Target group not found.', 'danger')
            return redirect(url_for('worker.campaigns', gid=c.group_id))

        records = ModuleRecord.query.filter_by(group_id=c.group_id).all()
        if not records:
            flash('No records found in this group.', 'warning')
            return redirect(url_for('worker.campaigns', gid=c.group_id))

        # Get Script
        script = Script.query.get(c.script_id)
        if not script:
            flash('Campaign has no associated script.', 'danger')
            return redirect(url_for('worker.campaigns', gid=c.group_id))

        # Get All Fields (Module Level + Group Level)
        all_fields = ModuleField.query.filter(
            (ModuleField.module_id == group.module_id) & 
            ((ModuleField.group_id == None) | (ModuleField.group_id == group.id))
        ).all()
        
        field_info = {f.id: f for f in all_fields}
        
        # Use boolean fields with defined logic as filters
        logic_fields = [f for f in all_fields if f.field_type == 'boolean' and (f.meta and f.meta.get('logic'))]

        eligible_count = 0
        count = 0
        print(f"DEBUG: Starting Campaign {c.id}. Found {len(records)} records. Filters: {[f.name for f in logic_fields]}")

        for r in records:
            # Check logic filters
            if logic_fields:
                is_eligible = True
                record_values = {v.field_id: v.value for v in r.values}
                for lf in logic_fields:
                    raw_val = record_values.get(lf.id)
                    # If value is missing, default to TRUE as per user request
                    val = str(raw_val).upper().strip() if raw_val is not None else "TRUE"
                    
                    if val == 'FALSE':
                        print(f"DEBUG: Record {r.id} rejected by '{lf.name}' (Value: {val})")
                        is_eligible = False
                        break
                if not is_eligible:
                    continue 

            eligible_count += 1
            print(f"DEBUG: Record {r.id} is ELIGIBLE.")

            # 1. Prepare record data map for placeholders
            record_data = {}
            contact_phone = None
            contact_id = None # We might need to map record to Contact or create one

            # Find or Create Contact for this record
            # Use field_type to identify the phone number reliably
            for v in r.values:
                field = field_info.get(v.field_id)
                if not field: continue
                
                record_data[field.name] = v.value
                
                # RELIABLE DETECTION: Use data type, not label
                if field.field_type == 'phone':
                    contact_phone = v.value

            # Fallback for older modules where field_type might not be 'phone' 
            # (though validation now enforces it, better safe)
            if not contact_phone:
                for v in r.values:
                    field = field_info.get(v.field_id)
                    if field and ('phone' in field.name.lower() or 'contact' in field.name.lower()):
                        contact_phone = v.value

            if not contact_phone:
                print(f"DEBUG: Record {r.id} missing phone field")
                continue
            
            print(f"DEBUG: Processing record {r.id}, phone {contact_phone}")

            # Ensure Contact exists in DB
            from models.models import Contact
            contact = Contact.query.filter_by(organization_id=c.organization_id, phone=contact_phone).first()
            if not contact:
                contact = Contact(organization_id=c.organization_id, phone=contact_phone, name=record_data.get('name', record_data.get('Name', 'Customer')))
                db.session.add(contact)
                db.session.flush()

            # 2. Process Content (Text + Audio)
            text_body = script.content
            voice_body = script.voice_content if script.voice_content else script.content
            
            # Replace placeholders {{field}} case-insensitively using regex
            import re
            for key, val in record_data.items():
                if val:
                    # Regex to match {{key}} case-insensitively
                    pattern = re.compile(re.escape('{{' + key + '}}'), re.IGNORECASE)
                    text_body = pattern.sub(str(val), text_body)
                    voice_body = pattern.sub(str(val), voice_body)
                    
                    # Also handle lowercase version if requested manually
                    pattern_lower = re.compile(re.escape('{{' + key.lower() + '}}'), re.IGNORECASE)
                    text_body = pattern_lower.sub(str(val), text_body)
                    voice_body = pattern_lower.sub(str(val), voice_body)

            # 3. Handle Dispatch
            try:
                if c.type == 'whatsapp_text':
                    # Check for Content API Sid in script meta
                    content_sid = script.meta.get('content_sid') if script.meta else None
                    content_variables = None
                    
                    if content_sid:
                        # Map placeholders to numeric keys if needed for Twilio Content API
                        # For now, let's use the user's example format if provided in meta or default
                        # Example: {"1": "val1", "2": "val2"}
                        import json
                        vars_map = {}
                        # Ensure we check both lowercase and original casing for the field name
                        raw_vars = script.meta.get('content_variables_map', {'1': 'name'})
                        for k, field_name in raw_vars.items():
                            val = record_data.get(field_name) or record_data.get(field_name.lower()) or record_data.get(field_name.capitalize()) or ''
                            vars_map[k] = str(val)
                        content_variables = json.dumps(vars_map)

                    print(f"DEBUG: Record {r.id} - Final Message: {text_body[:50]}...")

                    # Send Text Message (or Content Template)
                    dispatch_whatsapp(
                        c.organization_id, 
                        contact.id, 
                        message=text_body, 
                        campaign_id=c.id,
                        content_sid=content_sid,
                        content_variables=content_variables,
                        sender_number_id=c.sender_number_id
                    )
                    
                    # Also Send Voice Note if script has voice intent
                    voice_gen = get_voice_generator()
                    # FIX: Pass the script's language to the generator
                    lang_code = get_lang_code_for_generator(script.language)
                    audio_res = voice_gen.generate_generic_voice_message(voice_body, language=lang_code)
                    if audio_res['success']:
                        media_url = url_for('static', filename=f"audio/{audio_res['filename']}", _external=True)
                        dispatch_whatsapp(
                            c.organization_id, 
                            contact.id, 
                            audio_url=media_url, 
                            campaign_id=c.id,
                            local_path=audio_res.get('file_path'),
                            sender_number_id=c.sender_number_id
                        )
                        # Schedule deletion of transient voice note after 2 minutes
                        if audio_res.get('file_path'):
                            delete_transient_file(audio_res['file_path'], delay=120)
                
                elif c.type == 'call':
                    # Determine which service to use based on sender number
                    from models.models import CommunicationNumber
                    sender = CommunicationNumber.query.get(c.sender_number_id) if c.sender_number_id else None
                    print(f"DEBUG: Campaign {c.id} using Sender Number ID: {c.sender_number_id}, Type: {sender.channel_type if sender else 'None'}")
                    
                    if sender and sender.channel_type == 'indian_voice':
                        from services.exotel_service import make_exotel_call
                        make_exotel_call(
                            c.organization_id,
                            contact.id,
                            tts_text=text_body,
                            language=script.language,
                            campaign_id=c.id,
                            sender_number_id=c.sender_number_id
                        )
                    else:
                        from services.twilio_service import make_call
                        make_call(
                            c.organization_id, 
                            contact.id, 
                            tts_text=text_body, 
                            language=script.language, 
                            campaign_id=c.id,
                            sender_number_id=c.sender_number_id
                        )

                count += 1
                print(f"DEBUG: Dispatched {c.type} for record {r.id}")
            except Exception as e:
                print(f"DEBUG: Error in loop for record {r.id}: {e}")
                logger.error(f"Failed to dispatch campaign item for {contact_phone}: {e}")

        if eligible_count == 0:
            flash(f'Campaign finished, but 0 records were eligible based on your logic filters.', 'warning')
        else:
            flash(f'Campaign processed for {eligible_count} targets.', 'success')
        db.session.commit()

    except Exception as e:
        logger.exception("Campaign execution failed")
        flash(f'Error starting campaign: {str(e)}', 'danger')
    return redirect(url_for('worker.campaigns', gid=c.group_id))


@worker_bp.route('/groups/<int:gid>/records', methods=['POST'])
@worker_required
def add_record(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    # Get Fields Config (Merge module and group fields)
    fields = ModuleField.query.filter(
        (ModuleField.module_id == m.id) & 
        ((ModuleField.group_id == None) | (ModuleField.group_id == gid))
    ).all()
    
    # 1. Validation & Data Collection Loop
    form_data = {}
    files_to_save = {}

    import re
    
    for f in fields:
        input_name = f'field_{f.id}'
        
        # Handle File Uploads
        if f.field_type == 'file':
            if input_name in request.files:
                file = request.files[input_name]
                if file and file.filename:
                    files_to_save[f.id] = file
            continue

        # Handle Text/Numeric
        raw_val = request.form.get(input_name)
        
        # Type-Specific Validation
        if raw_val:
            if f.field_type == 'numeric':
                if not re.match(r'^-?\d+(\.\d+)?$', raw_val):
                    flash(f'Error: Field "{f.name}" requires a valid number.', 'danger')
                    return redirect(url_for('worker.group_dashboard', gid=gid))
            elif f.field_type == 'email':
                if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', raw_val):
                    flash(f'Error: Field "{f.name}" requires a valid email.', 'danger')
                    return redirect(url_for('worker.group_dashboard', gid=gid))
            elif f.field_type == 'phone':
                if not re.match(r'^\d{10}$', raw_val):
                    flash(f'Error: Field "{f.name}" must be exactly 10 digits.', 'danger')
                    return redirect(url_for('worker.group_dashboard', gid=gid))
        
        # Uniqueness Check
        if f.is_unique and raw_val:
            # Check if this value already exists for this field in this module (case-insensitive)
            from sqlalchemy import func
            duplicate = db.session.query(ModuleRecordValue).join(ModuleRecord).filter(
                ModuleRecordValue.field_id == f.id,
                func.lower(ModuleRecordValue.value) == func.lower(str(raw_val)),
                ModuleRecord.module_id == m.id
            ).first()
            if duplicate:
                # Silent fail as real-time validation handles user feedback
                return redirect(url_for('worker.group_dashboard', gid=gid))
        
        form_data[f.id] = raw_val

    # 2. Create Record Only if Validation Passes
    record = ModuleRecord(module_id=m.id, group_id=g.id)
    db.session.add(record)
    db.session.flush() # get ID for filenames
    
    # 3. Save Files
    import os
    from werkzeug.utils import secure_filename
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    upload_dir = os.path.join(base_dir, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    for fid, file in files_to_save.items():
        filename = secure_filename(file.filename)
        unique_filename = f"{record.id}_{fid}_{filename}"
        file.save(os.path.join(upload_dir, unique_filename))
        
        # Save as value
        rv = ModuleRecordValue(record_id=record.id, field_id=fid, value=f'uploads/{unique_filename}')
        db.session.add(rv)

    # 4. Save Text/Number Values
    for fid, val in form_data.items():
        if val is not None:
            rv = ModuleRecordValue(record_id=record.id, field_id=fid, value=str(val))
            db.session.add(rv)
            
    db.session.commit()
    flash('Record added successfully', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))

            
    db.session.commit()

    # Trigger Automation Engine
    try:
        from services.automation_engine import get_automation_engine
        ae = get_automation_engine()
        ae.recalculate_record(record.id)
    except Exception as e:
        logger.error(f"Automation Error: {e}")

    flash('Record added successfully', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))


@worker_bp.route('/groups/<int:gid>/export/template')
@worker_required
def export_template(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    import pandas as pd
    from io import BytesIO
    from flask import send_file
    
    # Create columns from field names
    fields = g.fields
    columns = [f.name for f in fields]
    df = pd.DataFrame(columns=columns)
    
    fmt = request.args.get('format', 'csv')
    output = BytesIO()
    
    if fmt == 'excel':
        df.to_excel(output, index=False)
        mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        filename = f"{m.name}_template.xlsx"
    else:
        df.to_csv(output, index=False)
        mimetype = 'text/csv'
        filename = f"{m.name}_template.csv"
        
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=filename, mimetype=mimetype)


@worker_bp.route('/groups/<int:gid>/export/data')
@worker_required
def export_data(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    import pandas as pd
    from io import BytesIO
    from flask import send_file
    
    # Prepare data
    data = []
    fields = g.fields
    field_map = {f.id: f.name for f in fields}
    columns = [f.name for f in fields]
    columns.append('Created At')
    
    for r in g.records:
        row = {}
        row['Created At'] = r.created_at.strftime('%Y-%m-%d %H:%M')
        for val in r.values:
            fname = field_map.get(val.field_id)
            if fname:
                row[fname] = val.value
        data.append(row)
        
    df = pd.DataFrame(data, columns=columns)
    
    fmt = request.args.get('format', 'csv')
    output = BytesIO()
    
    if fmt == 'excel':
        df.to_excel(output, index=False)
        mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        filename = f"{g.name}_data.xlsx"
    else:
        df.to_csv(output, index=False)
        mimetype = 'text/csv'
        filename = f"{g.name}_data.csv"
        
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=filename, mimetype=mimetype)


@worker_bp.route('/groups/<int:gid>/import', methods=['POST'])
@worker_required
def import_data(gid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected', 'danger')
        return redirect(url_for('worker.group_dashboard', gid=gid))
        
    import pandas as pd
    
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            flash('Invalid file format. Use CSV or Excel.', 'danger')
            return redirect(url_for('worker.group_dashboard', gid=gid))
            
        # Map Name -> Field Object
        fields = g.fields
        name_to_field = {f.name: f for f in fields}
        
        count = 0
        skipped = 0
        imported_ids = []
        for _, row in df.iterrows():
            # Check Uniqueness
            is_valid_row = True
            for col_name, value in row.items():
                if pd.isna(value): continue
                field = name_to_field.get(col_name)
                if field and field.is_unique:
                    # Check duplicate in DB
                    duplicate = db.session.query(ModuleRecordValue).join(ModuleRecord).filter(
                        ModuleRecordValue.field_id == field.id,
                        ModuleRecordValue.value == str(value),
                        ModuleRecord.module_id == m.id
                    ).first()
                    if duplicate:
                        is_valid_row = False
                        break
            
            if not is_valid_row:
                skipped += 1
                continue

            # Create Record
            record = ModuleRecord(module_id=m.id, group_id=g.id)
            db.session.add(record)
            db.session.flush()
            imported_ids.append(record.id)
            
            # Add Values
            for col_name, value in row.items():
                if pd.isna(value): continue
                field = name_to_field.get(col_name)
                if field:
                    val_str = str(value)
                    
                    # Type Validation during Import
                    import re
                    if field.field_type == 'numeric':
                        if not re.match(r'^-?\d+(\.\d+)?$', val_str):
                            is_valid_row = False
                            break
                    elif field.field_type == 'email':
                        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', val_str):
                            is_valid_row = False
                            break
                    elif field.field_type == 'phone':
                        if not re.match(r'^\d{10}$', val_str):
                            is_valid_row = False
                            break
                            
                    rv = ModuleRecordValue(record_id=record.id, field_id=field.id, value=val_str)
                    db.session.add(rv)
            count += 1
            
        db.session.commit()

        # Trigger Automation Engine for each record
        from services.automation_engine import get_automation_engine
        ae = get_automation_engine()
        for r_id in imported_ids:
             ae.recalculate_record(r_id)

        msg = f'Successfully imported {count} records.'
        if skipped > 0:
            msg += f' {skipped} rows skipped due to duplicate unique fields.'
        flash(msg, 'success' if count > 0 else 'warning')
        return redirect(url_for('worker.group_dashboard', gid=gid))
        
    except Exception as e:
        flash(f'Error importing file: {str(e)}', 'danger')
        return redirect(url_for('worker.group_dashboard', gid=gid))
        
@worker_bp.route('/groups/<int:gid>/records/<int:rid>', methods=['GET'])
@worker_required
def get_record(gid, rid):
    try:
        g = ModuleGroup.query.get_or_404(gid)
        m = Module.query.get(g.module_id)
        if m.organization_id != current_user.organization_id:
            return jsonify({'error': 'Access denied'}), 403
        
        r = ModuleRecord.query.get_or_404(rid)
        if r.group_id != gid:
            return jsonify({'error': 'Record mismatch'}), 400
            
        data = {'id': r.id, 'values': {}}
        for v in r.values:
            data['values'][v.field_id] = v.value
            
        return jsonify(data)
    except Exception as e:
        print(f"Error in get_record: {str(e)}")
        return jsonify({'error': str(e)}), 500

@worker_bp.route('/groups/<int:gid>/records/<int:rid>/update', methods=['POST'])
@worker_required
def update_record(gid, rid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    r = ModuleRecord.query.get_or_404(rid)
    
    import os
    from werkzeug.utils import secure_filename
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    upload_dir = os.path.join(base_dir, 'static', 'uploads')
    
    for field in g.fields:
        key = f'field_{field.id}'
        rv = ModuleRecordValue.query.filter_by(record_id=r.id, field_id=field.id).first()
        
        if field.field_type == 'file':
            if key in request.files:
                file = request.files[key]
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    unique_filename = f"{r.id}_{field.id}_{filename}"
                    file.save(os.path.join(upload_dir, unique_filename))
                    
                    if not rv:
                        rv = ModuleRecordValue(record_id=r.id, field_id=field.id)
                        db.session.add(rv)
                    rv.value = f'uploads/{unique_filename}'
        else:
            val = request.form.get(key)
            if val is not None:
                # Validation
                import re
                if field.field_type == 'numeric' and val:
                    if not re.match(r'^-?\d+(\.\d+)?$', val):
                        flash(f'Error: Field "{field.name}" requires a valid number.', 'danger')
                        return redirect(url_for('worker.group_dashboard', gid=gid))
                        
                # Uniqueness Check
                if field.is_unique and val:
                    from sqlalchemy import func
                    duplicate = db.session.query(ModuleRecordValue).join(ModuleRecord).filter(
                        ModuleRecordValue.field_id == field.id,
                        func.lower(ModuleRecordValue.value) == func.lower(str(val)),
                        ModuleRecord.module_id == m.id,
                        ModuleRecord.id != r.id # Exclude current record
                    ).first()
                    if duplicate:
                        # Silent fail as real-time validation handles user feedback
                        return redirect(url_for('worker.group_dashboard', gid=gid))

                if not rv:
                    rv = ModuleRecordValue(record_id=r.id, field_id=field.id)
                    db.session.add(rv)
                rv.value = str(val)
                
    db.session.commit()

    # Trigger Automation Engine
    try:
        from services.automation_engine import get_automation_engine
        ae = get_automation_engine()
        ae.recalculate_record(r.id)
    except Exception as e:
        logger.error(f"Automation Error: {e}")

    flash('Record updated successfully', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))

@worker_bp.route('/groups/<int:gid>/records/<int:rid>/delete', methods=['POST'])
@worker_required
def delete_record(gid, rid):
    g = ModuleGroup.query.get_or_404(gid)
    m = Module.query.get(g.module_id)
    if m.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    r = ModuleRecord.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    flash('Record deleted', 'success')
    return redirect(url_for('worker.group_dashboard', gid=gid))


@worker_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@worker_bp.route('/campaigns/<int:cid>/report')
@worker_required
def campaign_report(cid):
    c = Campaign.query.get_or_404(cid)
    if c.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    logs = DeliveryLog.query.filter_by(campaign_id=cid).order_by(DeliveryLog.created_at.desc()).all()
    
    # Analytics
    total = len(logs)
    status_counts = {}
    start_time = None
    end_time = None
    
    for l in logs:
        status_counts[l.status] = status_counts.get(l.status, 0) + 1
        if not start_time or l.created_at < start_time:
            start_time = l.created_at
        if not end_time or l.created_at > end_time:
            end_time = l.created_at
            
    # If no logs but campaign exists, use campaign creation as start
    if not start_time:
        start_time = c.created_at
        
    return render_template(
        'worker/campaign_report.html', 
        campaign=c, 
        logs=logs, 
        stats={
            'total': total,
            'counts': status_counts,
            'start': start_time,
            'end': end_time
        }
    )


@worker_bp.route('/campaigns/<int:cid>/delete', methods=['POST'])
@worker_required
def delete_campaign(cid):
    c = Campaign.query.get_or_404(cid)
    if c.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
    
    gid = c.group_id
    db.session.delete(c)
    db.session.commit()
    flash('Campaign deleted', 'success')
    return redirect(url_for('worker.campaigns', gid=gid))


@worker_bp.route('/campaigns/<int:cid>/download')
@worker_required
def download_report(cid):
    c = Campaign.query.get_or_404(cid)
    if c.organization_id != current_user.organization_id:
        flash('Access denied', 'danger')
        return redirect(url_for('worker.dashboard'))
        
    import csv
    import io
    from flask import Response
    
    logs = DeliveryLog.query.filter_by(campaign_id=cid).order_by(DeliveryLog.created_at.asc()).all()
    
    # Generate CSV
    def generate():
        data = io.StringIO()
        w = csv.writer(data)
        
        # Header
        w.writerow(('Date', 'Contact ID', 'Channel', 'Status', 'Error', 'Meta'))
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        for l in logs:
            w.writerow((
                l.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                l.contact_id,
                l.channel,
                l.status,
                l.error,
                str(l.meta)
            ))
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)
            
    headers = {
        'Content-Disposition': f'attachment; filename=campaign_{cid}_report.csv',
        'Content-Type': 'text/csv'
    }
    return Response(generate(), mimetype='text/csv', headers=headers)
