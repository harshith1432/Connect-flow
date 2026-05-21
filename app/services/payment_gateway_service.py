from app.models.platform import PaymentGateway

class PaymentGatewayService:
    @staticmethod
    def get_active_gateways():
        """Retrieve all active payment gateways sorted by priority."""
        return PaymentGateway.query.filter_by(active=True).order_by(PaymentGateway.priority.desc()).all()

    @staticmethod
    def get_gateway_by_id(gateway_id):
        """Retrieve a specific gateway by its ID."""
        return PaymentGateway.query.get(gateway_id)
    
    @staticmethod
    def get_gateway_by_provider(provider):
        """Retrieve a specific active gateway by its provider (e.g., 'razorpay')."""
        return PaymentGateway.query.filter_by(provider=provider, active=True).first()
