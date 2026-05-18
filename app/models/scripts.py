from app.extensions import db


class Script(db.Model):
    __tablename__ = "scripts"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    language = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # whatsapp_text, call
    content = db.Column(db.Text, nullable=False)
    meta = db.Column(db.JSON)
