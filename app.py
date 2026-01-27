import os
from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text

from config import Config

# Initialize extensions in app context
from models import db

login_manager = LoginManager()
csrf = CSRFProtect()



def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize DB, Migrate and Login
    db.init_app(app)
    migrate = Migrate(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.index'

    # loader: try platform admin then organization users
    @login_manager.user_loader
    def load_user(user_id):
        from models.models import PlatformAdmin, OrganizationUser
        u = PlatformAdmin.query.get(int(user_id))
        if u:
            return u
        return OrganizationUser.query.get(int(user_id))

    # Register blueprints
    from routes.main import main_bp
    from routes.admin import admin_bp
    from routes.org import org_bp
    from routes.worker import worker_bp
    from routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    # Temporary: exempt the organization registration endpoint from CSRF while
    # debugging token issues in local dev. Remove this exemption once CSRF
    # flow is validated and working for clients.
    try:
        csrf.exempt(main_bp.view_functions['main.org_register'])
    except Exception:
        pass
    # Platform owner routes are intentionally prefixed with /platform to isolate them
    app.register_blueprint(admin_bp, url_prefix='/platform')
    # Exempt platform blueprint from CSRF checks to ensure login page loads reliably.
    # The platform area is still protected by role checks; consider adding per-route CSRF later.
    csrf.exempt(admin_bp)
    csrf.exempt(api_bp)
    app.register_blueprint(org_bp, url_prefix='/org')
    app.register_blueprint(worker_bp, url_prefix='/worker')

    # Ensure platform admin exists and DB connectivity on startup
    from sqlalchemy import text
    with app.app_context():
        from models.models import PlatformAdmin
        try:
            # Try a simple connection check; use text() to satisfy SQLAlchemy's requirement
            db.session.execute(text('SELECT 1'))
        except Exception as e:
            # Re-raise with clearer message so startup fails loudly in production
            raise RuntimeError(f'Unable to connect to the database: {e}')

        # Create tables if they do not exist (for development). Production should use migrations.
        db.create_all()
        admin = PlatformAdmin.query.filter_by(email=Config.DEFAULT_ADMIN_EMAIL).first()
        if not admin:
            # Create default platform admin using env-configured credentials
            admin = PlatformAdmin.create_default()
            db.session.add(admin)
            db.session.commit()
    return app


    return app




if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
