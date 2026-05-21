import razorpay
import hmac
import hashlib

class PaymentDispatcher:
    """
    Dynamically routes payment operations to the correct SDK based on the PaymentGateway model.
    """

    @staticmethod
    def create_order(gateway, amount, currency="INR", receipt=None):
        """
        Creates an order with the specific gateway provider.
        amount should be in smallest currency unit (e.g. paise for INR)
        """
        if gateway.provider.lower() == "razorpay":
            return PaymentDispatcher._create_razorpay_order(gateway, amount, currency, receipt)
        elif gateway.provider.lower() == "stripe":
            return PaymentDispatcher._create_stripe_order(gateway, amount, currency, receipt)
        else:
            raise ValueError(f"Unsupported payment provider: {gateway.provider}")

    @staticmethod
    def verify_payment(gateway, response_data):
        """
        Verifies payment signature based on gateway provider.
        """
        if gateway.provider.lower() == "razorpay":
            return PaymentDispatcher._verify_razorpay_payment(gateway, response_data)
        elif gateway.provider.lower() == "stripe":
            return PaymentDispatcher._verify_stripe_payment(gateway, response_data)
        else:
            raise ValueError(f"Unsupported payment provider: {gateway.provider}")

    # --- Razorpay Implementation ---

    @staticmethod
    def _get_razorpay_client(gateway):
        from flask import current_app
        client_key = current_app.config.get("RAZORPAY_KEY_ID") or gateway.client_key
        secret_key = current_app.config.get("RAZORPAY_KEY_SECRET") or gateway.secret_key
        return razorpay.Client(auth=(client_key, secret_key))

    @staticmethod
    def _create_razorpay_order(gateway, amount, currency, receipt):
        from flask import current_app
        client_key = current_app.config.get("RAZORPAY_KEY_ID") or gateway.client_key
        secret_key = current_app.config.get("RAZORPAY_KEY_SECRET") or gateway.secret_key

        client = razorpay.Client(auth=(client_key, secret_key))
        order_data = {
            "amount": int(amount),
            "currency": currency,
            "receipt": receipt
        }
        order = client.order.create(data=order_data)
        return {
            "provider_order_id": order.get("id"),
            "order_id": order.get("id"),  # compatibility with frontend expected order_id
            "amount": order.get("amount"),
            "currency": order.get("currency"),
            "gateway_id": gateway.id,
            "provider": "razorpay",
            "client_key": client_key,  # Send to frontend for initialization
            "key_id": client_key,  # compatibility with frontend expected key_id
            "logo": gateway.logo
        }

    @staticmethod
    def _verify_razorpay_payment(gateway, response_data):
        """
        response_data should contain: razorpay_payment_id, razorpay_order_id, razorpay_signature
        """
        from flask import current_app
        razorpay_order_id = response_data.get("razorpay_order_id")
        razorpay_payment_id = response_data.get("razorpay_payment_id")
        razorpay_signature = response_data.get("razorpay_signature")

        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return False, "Missing Razorpay verification parameters"

        # Generate signature
        key_secret = current_app.config.get("RAZORPAY_KEY_SECRET") or gateway.secret_key
        msg = f"{razorpay_order_id}|{razorpay_payment_id}"
        generated_signature = hmac.new(
            key_secret.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if generated_signature == razorpay_signature:
            return True, "Signature verified successfully"
        else:
            return False, "Invalid signature"

    # --- Stripe Implementation (Placeholder for future) ---
    
    @staticmethod
    def _create_stripe_order(gateway, amount, currency, receipt):
        # Implementation for stripe goes here
        raise NotImplementedError("Stripe integration is pending")

    @staticmethod
    def _verify_stripe_payment(gateway, response_data):
        # Implementation for stripe verification goes here
        raise NotImplementedError("Stripe integration is pending")

