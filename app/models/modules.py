from datetime import datetime
from sqlalchemy.orm import relationship, backref
from app.extensions import db


class Module(db.Model):
    __tablename__ = "modules"
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("organization_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    creator = relationship("OrganizationUser", foreign_keys=[created_by_id])

    fields = relationship("ModuleField", backref="module", cascade="all, delete-orphan")
    groups = relationship("ModuleGroup", backref="module", cascade="all, delete-orphan")


class ModuleGroup(db.Model):
    __tablename__ = "module_groups"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    records = relationship(
        "ModuleRecord", backref="group", cascade="all, delete-orphan"
    )
    scripts = relationship("Script", backref="group", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", backref="group", cascade="all, delete-orphan")


class ModuleField(db.Model):
    __tablename__ = "module_fields"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    name = db.Column(db.String(255), nullable=False)
    field_type = db.Column(db.String(50), default="string")
    is_unique = db.Column(db.Boolean, default=False)
    meta = db.Column(db.JSON)

    group = relationship(
        "ModuleGroup", backref=backref("fields", cascade="all, delete-orphan")
    )

    @property
    def options(self):
        """Returns a list of options for dropdown/multiple choice fields."""
        if not self.meta:
            return []
        import json

        if isinstance(self.meta, str):
            try:
                meta_dict = json.loads(self.meta)
            except:
                return []
        else:
            meta_dict = self.meta
        return meta_dict.get("options", [])


class ModuleRecord(db.Model):
    __tablename__ = "module_records"
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("modules.id", ondelete="CASCADE"))
    group_id = db.Column(
        db.Integer, db.ForeignKey("module_groups.id", ondelete="CASCADE"), nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("organization_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    values = relationship(
        "ModuleRecordValue", backref="record", cascade="all, delete-orphan"
    )

    @property
    def field_values(self):
        """Returns a dictionary mapping field_id to its value."""
        return {v.field_id: v.value for v in self.values}

    @property
    def named_values(self):
        """Returns a dictionary mapping field name to its value.
        
        Field names are stripped of leading/trailing whitespace to handle
        CSV column headers with extra spaces (e.g., 'number ' -> 'number').
        """
        return {v.field.name.strip(): v.value for v in self.values if v.field}


class ModuleRecordValue(db.Model):
    __tablename__ = "module_record_values"
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(
        db.Integer, db.ForeignKey("module_records.id", ondelete="CASCADE")
    )
    field_id = db.Column(
        db.Integer, db.ForeignKey("module_fields.id", ondelete="CASCADE")
    )
    value = db.Column(db.Text)

    field = db.relationship("ModuleField", foreign_keys=[field_id])
