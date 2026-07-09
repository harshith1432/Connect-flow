import uuid
import os
from flask import request, redirect, session, g
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

def log_debug(message):
    try:
        os.makedirs("logs", exist_ok=True)
        with open("logs/hook_debug.log", "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception as e:
        pass

def setup_session_scoping(app):
    # Register hooks on the app
    
    def before_request_scoping():
        # Exclude static assets
        if request.path.startswith("/static/") or request.path.startswith("/static"):
            return
            
        # Only apply session scoping to authenticated/dashboard blueprints and auth screens
        scoped_prefixes = ("/org", "/platform", "/worker", "/security", "/campaign-express", "/login", "/register")
        if not any(request.path.startswith(prefix) for prefix in scoped_prefixes):
            return
            
        # Get tid from request (query string or form data)
        tid = request.args.get('tid') or request.form.get('tid')
        
        # Fallback: Parse tid from Referer header if it is an AJAX or resource request
        if not tid and request.headers.get("Referer"):
            try:
                referer_parts = urlparse(request.headers.get("Referer"))
                referer_query = dict(parse_qsl(referer_parts.query))
                tid = referer_query.get('tid')
            except Exception:
                pass
        
        # If tid is missing and it's a GET request expecting HTML, redirect to add a new tid
        is_html_get = request.method == "GET" and "text/html" in request.headers.get("Accept", "")
        
        log_debug(f"[BEFORE] path={request.path}, method={request.method}, tid={tid}, session={dict(session)}")
        
        if not tid and is_html_get:
            new_tid = str(uuid.uuid4())[:8]
            parts = urlparse(request.url)
            query = dict(parse_qsl(parts.query))
            query['tid'] = new_tid
            new_query = urlencode(query)
            new_url = urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
            log_debug(f"[BEFORE] Redirecting to add tid: {new_url}")
            return redirect(new_url)
            
        if tid:
            g.tid = tid
            
            # Map default _user_id to the scoped dict in session
            if '_user_ids' not in session:
                session['_user_ids'] = {}
                
            # Handle legacy/existing session where _user_id exists but _user_ids map is empty
            if '_user_id' in session and not session['_user_ids']:
                session['_user_ids'][tid] = session['_user_id']
                
            # Swap _user_id in session dynamically for Flask-Login based on the tab ID (tid)
            if tid in session['_user_ids']:
                session['_user_id'] = session['_user_ids'][tid]
            else:
                # Inherit active session if another tab is already logged in for the same portal/role
                inherited_user_id = None
                target_prefix = None
                target_role = None
                
                if request.path.startswith("/platform"):
                    target_prefix = "platform_admin:"
                elif request.path.startswith("/org"):
                    target_prefix = "organization_user:"
                    target_role = "org_admin"
                elif request.path.startswith("/worker"):
                    target_prefix = "organization_user:"
                    target_role = "worker"
                elif request.path.startswith("/campaign-express"):
                    target_prefix = "campaign_express_user:"
                elif request.path.startswith("/security"):
                    pre_mfa = session.get("pre_mfa_user_type")
                    if pre_mfa == "platform_admin":
                        target_prefix = "platform_admin:"
                    elif pre_mfa == "org_user":
                        target_prefix = "organization_user:"
                        target_role = "org_admin"
                    elif pre_mfa == "campaign_express":
                        target_prefix = "campaign_express_user:"
                        
                if target_prefix and '_user_ids' in session:
                    for val in session['_user_ids'].values():
                        if val and val.startswith(target_prefix):
                            # Differentiate between org admin and worker role under same organization_user model prefix
                            if target_prefix == "organization_user:" and target_role:
                                try:
                                    from app.extensions import db
                                    from app.models import OrganizationUser
                                    real_id = int(val.split(":", 1)[1])
                                    user = db.session.get(OrganizationUser, real_id)
                                    if user and user.role == target_role:
                                        inherited_user_id = val
                                        break
                                except Exception:
                                    pass
                            else:
                                inherited_user_id = val
                                break
                            
                if inherited_user_id:
                    session['_user_ids'][tid] = inherited_user_id
                    session['_user_id'] = inherited_user_id
                else:
                    session.pop('_user_id', None)
                
            log_debug(f"[BEFORE] AFTER SWAP: _user_id={session.get('_user_id')}, _user_ids={session.get('_user_ids')}")

    # Register at the very beginning of the before_request pipeline
    app.before_request_funcs.setdefault(None, []).insert(0, before_request_scoping)
                
    @app.after_request
    def after_request_scoping(response):
        # Only rewrite local redirects to propagate tid
        tid = getattr(g, 'tid', None)
        if tid:
            log_debug(f"[AFTER] path={request.path}, status={response.status_code}, tid={tid}, session_before={dict(session)}")
            # 1. Update redirected location if it exists
            if response.status_code in [301, 302, 303, 307, 308]:
                location = response.headers.get('Location')
                if location:
                    if location.startswith('/') or location.startswith(request.host_url):
                        parts = urlparse(location)
                        
                        # Bypass query string rewrite for login/auth pages to prevent double encoding and parameter bloating
                        is_login_redirect = any(x in parts.path for x in ["/login", "/register", "/forgot-password", "/verify-otp"]) or parts.path == "/"
                        
                        if not is_login_redirect:
                            query = dict(parse_qsl(parts.query))
                            if 'tid' not in query:
                                query['tid'] = tid
                                new_query = urlencode(query)
                                new_location = urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
                                response.headers['Location'] = new_location
                                log_debug(f"[AFTER] Rewrote redirect Location: {new_location}")
                            
            # 2. Persist the current request's user ID back into the tab's dict slot
            if '_user_ids' not in session:
                session['_user_ids'] = {}
                
            if '_user_id' in session:
                session['_user_ids'][tid] = session['_user_id']
            else:
                session['_user_ids'].pop(tid, None)
                
            session.modified = True
            log_debug(f"[AFTER] AFTER SAVE: session_after={dict(session)}")
            
        return response

