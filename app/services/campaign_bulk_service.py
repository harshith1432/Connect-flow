from app.extensions import db
from app.models import Campaign, Script, ModuleGroup
from app.services.campaign_runner import CampaignRunner
import csv
import io

class CampaignBulkService:
    @staticmethod
    def _get_campaigns(ids, org_id):
        return Campaign.query.filter(
            Campaign.id.in_(ids),
            Campaign.organization_id == org_id
        ).all()

    @staticmethod
    def execute_delete(ids, org_id):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        if not campaigns:
            return {"success": False, "error": "No campaigns found"}
        
        try:
            count = len(campaigns)
            for c in campaigns:
                db.session.delete(c)
            db.session.commit()
            return {"success": True, "deleted": count}
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_start(ids, org_id):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        if not campaigns:
            return {"success": False, "error": "No campaigns found"}
            
        try:
            count = 0
            for c in campaigns:
                if c.status == "running":
                    continue
                if not c.script_id:
                    raise Exception(f"Campaign '{c.name}' has no script attached.")
                if not c.group_id:
                    raise Exception(f"Campaign '{c.name}' has no group.")
                    
                c.status = "running"
                CampaignRunner.start(c.id)
                count += 1
                
            db.session.commit()
            return {"success": True, "started": count}
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_status_update(ids, org_id, new_status):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        try:
            for c in campaigns:
                c.status = new_status
            db.session.commit()
            return {"success": True, "updated": len(campaigns)}
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_duplicate(ids, org_id):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        try:
            count = 0
            new_ids = []
            for c in campaigns:
                new_c = Campaign(
                    organization_id=c.organization_id,
                    module_id=c.module_id,
                    group_id=c.group_id,
                    name=f"{c.name} (Copy)",
                    type=c.type,
                    script_id=c.script_id,
                    sender_number_id=c.sender_number_id,
                    filters=c.filters,
                    status="draft"
                )
                db.session.add(new_c)
                db.session.flush()
                new_ids.append(new_c.id)
                count += 1
            db.session.commit()
            return {"success": True, "duplicated": count, "new_ids": new_ids}
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_assign(ids, org_id, script_id):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        try:
            for c in campaigns:
                c.script_id = script_id
            db.session.commit()
            return {"success": True, "assigned": len(campaigns)}
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_move(ids, org_id, group_id):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        try:
            for c in campaigns:
                c.group_id = group_id
            db.session.commit()
            return {"success": True, "moved": len(campaigns)}
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_export(ids, org_id):
        campaigns = CampaignBulkService._get_campaigns(ids, org_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Name", "Status", "Type", "Created At"])
        for c in campaigns:
            writer.writerow([
                c.id,
                c.name,
                c.status,
                c.type,
                c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else ""
            ])
        return output.getvalue()
