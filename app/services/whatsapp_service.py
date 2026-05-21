import logging
import os
from datetime import datetime
from flask import current_app

# Setup HoomanLabs logger
hooman_logger = logging.getLogger("hoomanlabs")
hooman_logger.setLevel(logging.INFO)

# Make sure logs directory exists
log_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(log_dir, exist_ok=True)
fh = logging.FileHandler(os.path.join(log_dir, "hoomanlabs.log"))
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
hooman_logger.addHandler(fh)

class WhatsAppService:
    @staticmethod
    def send_fallback(campaign_target, phone, message_text):
        """
        Sends a WhatsApp fallback message and logs the outcome.
        In a real application, this would call a real WhatsApp API (like Twilio).
        """
        from app.core.logging_system import log_api_call, log_activity

        try:
            hooman_logger.info(f"[WhatsApp] Sending fallback to {phone} for target {campaign_target.id}. Message: {message_text}")
            log_api_call("WhatsApp", f"Fallback → {phone}")

            # Here we would use the actual WhatsApp provider (e.g. Twilio)
            # Example: 
            # client = Client(current_app.config['TWILIO_ACCOUNT_SID'], current_app.config['TWILIO_AUTH_TOKEN'])
            # message = client.messages.create(
            #     body=message_text,
            #     from_=current_app.config['TWILIO_WHATSAPP_NUMBER'],
            #     to=f"whatsapp:{phone}"
            # )
            
            # For now, simulate success
            delivered = True
            
            if delivered:
                hooman_logger.info(f"[WhatsApp] Delivered fallback to {phone}")
                log_api_call("WhatsApp", f"Delivered → {phone}", status="ok")
                campaign_target.whatsapp_sent = True
                return True
            else:
                hooman_logger.error(f"[WhatsApp] Failed to deliver fallback to {phone}")
                log_api_call("WhatsApp", f"Failed → {phone}", status="error")
                return False
                
        except Exception as e:
            hooman_logger.error(f"[WhatsApp] Error sending fallback to {phone}: {str(e)}")
            log_activity("WHATSAPP", f"Error: {str(e)}", level="error")
            return False
