from app import create_app
from app.extensions import db
from sqlalchemy import text
app = create_app()
app.app_context().push()
subs = db.session.execute(text('SELECT * FROM subscriptions')).fetchall()
print('All Subscriptions:', subs)
