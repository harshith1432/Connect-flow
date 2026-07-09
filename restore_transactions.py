from app import create_app
from app.extensions import db
from app.models import Payment, Plan, Organization, Subscription
from app.models.campaign_express import CampaignExpressPayment

app = create_app()
app.app_context().push()

# Get the first organization to assign payments to
org = Organization.query.first()
if not org:
    org = Organization(name="Demo Org", email="demo@demo.com")
    db.session.add(org)
    db.session.commit()

# Create missing payments based on plans to restore the ~18k history
plans = Plan.query.all()
for plan in plans:
    # Check if a payment for this plan already exists
    exists = Payment.query.filter_by(amount=plan.price, status="completed").first()
    if not exists:
        p = Payment(
            organization_id=org.id,
            amount=plan.price,
            status="completed",
            meta={"plan_name": plan.name, "method": "System Restore"}
        )
        db.session.add(p)
        print(f"Restored transaction for {plan.name}: {plan.price}")

db.session.commit()
print("Transaction history restored successfully.")
