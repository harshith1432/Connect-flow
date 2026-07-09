import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.abspath("."))

from app import create_app
from app.extensions import db
from app.models.platform import Plan

def seed():
    app = create_app()
    with app.app_context():
        print("Seeding and aligning default subscription plans...")
        default_plans = [
            {
                "name": "Free Trial",
                "description": "Perfect for testing outbound outreach scripts",
                "price": 0.00,
                "billing_interval": "monthly",
                "features": ["5 Worker Accounts", "1,000 Automated Broadcasts/mo", "2 Custom Modules", "3 Active Campaigns", "Basic Delivery Analytics"],
                "is_active": True
            },
            {
                "name": "Growth",
                "description": "For active outbound lists and communication support",
                "price": 3499.00,
                "billing_interval": "monthly",
                "features": ["15 Worker Accounts", "15,000 Automated Broadcasts/mo", "5 Custom Modules", "15 Active Campaigns", "WhatsApp Messaging Channel", "Edge-TTS Speech Engine"],
                "is_active": True
            },
            {
                "name": "Professional",
                "description": "For high-volume outreach and team campaigns",
                "price": 12999.00,
                "billing_interval": "monthly",
                "features": ["50 Worker Accounts", "75,000 Automated Broadcasts/mo", "Unlimited Custom Modules", "50 Active Campaigns", "Twilio & Hooman custom API keys", "Priority Email & Chat Support"],
                "is_active": True
            },
            {
                "name": "Enterprise",
                "description": "Dedicated delivery channels and priority support",
                "price": 49999.00,
                "billing_interval": "monthly",
                "features": ["Unlimited Worker Accounts", "Unlimited Broadcasts & Campaigns", "White-label Branding Options", "Dedicated Deliverability SLA", "99.9% Uptime SLA", "24/7 Account Manager"],
                "is_active": True
            }
        ]

        active_names = [dp["name"] for dp in default_plans]

        # Deactivate old/deprecated plans
        for p in Plan.query.all():
            if p.name not in active_names:
                p.is_active = False
                print(f"Deactivated deprecated plan: {p.name}")

        # Add or update default plans
        for dp in default_plans:
            plan = Plan.query.filter_by(name=dp["name"]).first()
            if not plan:
                plan = Plan(
                    name=dp["name"],
                    description=dp["description"],
                    price=dp["price"],
                    billing_interval=dp["billing_interval"],
                    features=dp["features"],
                    is_active=dp["is_active"]
                )
                db.session.add(plan)
                print(f"Created plan: {dp['name']}")
            else:
                # Update existing plan details to ensure exact match
                plan.description = dp["description"]
                plan.price = dp["price"]
                plan.billing_interval = dp["billing_interval"]
                plan.features = dp["features"]
                plan.is_active = dp["is_active"]
                print(f"Aligned/updated plan: {dp['name']}")
        
        db.session.commit()
        print("Subscription plans seeded and aligned successfully!")

if __name__ == "__main__":
    seed()
