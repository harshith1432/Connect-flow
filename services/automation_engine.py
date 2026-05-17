import logging
from .logic_engine import get_logic_engine
from models import db
from models.models import (
    ModuleRecord,
    ModuleRecordValue,
    ModuleField,
    Contact,
    Organization,
)
from communication.whatsapp_dispatcher import dispatch_whatsapp

logger = logging.getLogger(__name__)


class AutomationEngine:
    def __init__(self):
        self.logic_engine = get_logic_engine()

    def recalculate_record(self, record_id):
        """
        Recalculates all calculated and boolean fields for a given record.
        """
        record = db.session.get(ModuleRecord, record_id)
        if not record:
            return

        # Get all fields for this module
        fields = ModuleField.query.filter_by(module_id=record.module_id).all()
        field_map = {f.id: f for f in fields}
        name_to_id = {f.name: f.id for f in fields}

        # Get current values
        current_values = record.field_values
        context = {f.name: current_values.get(f.id) for f in fields}

        trigger_actions = []

        # We need to handle dependencies. For simplicity, we'll do multiple passes
        # or just hope the order in fields list is mostly fine.
        # A better way is to build a dependency graph.
        # For now, let's just do two passes: calculated, then boolean.

        # Pass 1: Calculated Fields
        for f in fields:
            if f.field_type == "calculated":
                formula = f.meta.get("formula") if f.meta else None
                if formula:
                    new_val = self.logic_engine.evaluate_formula(formula, context)
                    self._update_record_value(record.id, f.id, str(new_val))
                    context[f.name] = new_val  # Update context for next fields

        # Pass 2: Boolean Fields
        for f in fields:
            if f.field_type == "boolean":
                logic = f.meta.get("logic") if f.meta else None
                if logic:
                    result = self.logic_engine.evaluate_boolean(logic, context)
                    self._update_record_value(
                        record.id, f.id, "TRUE" if result else "FALSE"
                    )
                    context[f.name] = result

        db.session.commit()

    def _update_record_value(self, record_id, field_id, value):
        rv = ModuleRecordValue.query.filter_by(
            record_id=record_id, field_id=field_id
        ).first()
        if not rv:
            rv = ModuleRecordValue(record_id=record_id, field_id=field_id)
            db.session.add(rv)
        rv.value = value


def get_automation_engine():
    return AutomationEngine()
