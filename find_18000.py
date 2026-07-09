from app import create_app
from app.extensions import db
from sqlalchemy import text
app = create_app()
app.app_context().push()
tables = db.session.execute(text('SELECT relname FROM pg_stat_user_tables')).fetchall()
for t, in tables:
    try:
        cols = db.session.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}' AND data_type IN ('integer', 'numeric', 'double precision', 'real')")).fetchall()
        for c, in cols:
            res = db.session.execute(text(f'SELECT SUM({c}) FROM {t}')).scalar()
            if res and 17000 < float(res) < 20000:
                print('FOUND', t, c, res)
    except Exception:
        db.session.rollback()
print('Done')
