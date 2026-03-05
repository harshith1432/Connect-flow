import os
import requests
import logging
from flask import current_app
from models import db
from models.models import DeliveryLog, Organization, CommunicationNumber, Contact

logger = logging.getLogger(__name__)

def _get_myoperator_context(organization_id, sender_number_id=None, channel_type='voice'):
    """
    Returns (token, myoperator_number) based on organization config or defaults.
    """
    org = Organization.query.get(organization_id)
    custom_conf = org.twilio_config.get('myoperator', {}) if org and org.twilio_config else {}
    
    token = custom_conf.get('token') or os.getenv('MYOPERATOR_TOKEN')
    secret_key = custom_conf.get('secret_key')
    x_api_key = custom_conf.get('x_api_key')
    company_id = custom_conf.get('company_id')
    ivr_id = custom_conf.get('ivr_id')
    
    # Default fallback based on channel type
    if channel_type == 'whatsapp':
        myoperator_number = custom_conf.get('wa_number') or custom_conf.get('number')
    else:
        myoperator_number = custom_conf.get('number')

    if sender_number_id:
        sender_record = CommunicationNumber.query.get(sender_number_id)
        if sender_record and sender_record.organization_id == organization_id and sender_record.active:
            myoperator_number = sender_record.number
            print(f"DEBUG: Using MyOperator Number from DB: {myoperator_number}")
    
    return token, myoperator_number, secret_key, x_api_key, company_id, ivr_id

def make_myoperator_call(organization_id, contact_id, tts_text, language='English', campaign_id=None, sender_number_id=None):
    """
    Initiate a voice call via MyOperator Public API.
    """
    logger.info("make_myoperator_call invoked for Org %s, Contact %s, Sender %s", organization_id, contact_id, sender_number_id)
    
    log = DeliveryLog(campaign_id=campaign_id, contact_id=contact_id, channel='call', status='queued')
    db.session.add(log)
    db.session.commit()

    token, sender_number, secret_key, x_api_key, company_id, ivr_id = _get_myoperator_context(organization_id, sender_number_id=sender_number_id, channel_type='voice')

    if not token and not x_api_key:
        log.status = 'failed'
        log.error = 'MyOperator credentials (Token or X-API-KEY) not configured'
        db.session.commit()
        return log

    if not sender_number:
        log.status = 'failed'
        log.error = 'MyOperator sender number not found'
        db.session.commit()
        return log

    contact = Contact.query.get(contact_id)
    if not contact:
        log.status = 'failed'
        log.error = 'Contact not found'
        db.session.commit()
        return log

    to_num = contact.phone
    import re
    to_num = re.sub(r'\D', '', to_num)
    if len(to_num) == 10:
        to_num = '91' + to_num

    # Determine if we use OBD API (v2-ish) or Connect API (v1)
    if x_api_key and secret_key and company_id:
        # OBD API (Outbound Dialer)
        # Endpoint: https://obd-api.myoperator.co/obd-api-v1
        url = "https://obd-api.myoperator.co/obd-api-v1"
        headers = {
            'x-api-key': x_api_key,
            'Content-Type': 'application/json'
        }
        payload = {
            'company_id': company_id,
            'secret_token': secret_key,
            'type': '1', # 1 for connect call
            'number': to_num,
            'number_2': re.sub(r'\D', '', sender_number)
        }
        if ivr_id:
            payload['public_ivr_id'] = ivr_id
            
        is_json_request = True
    else:
        # Legacy Connect API
        # Endpoint: https://api.myoperator.co/v1/voice/outbound/connect
        url = "https://api.myoperator.co/v1/voice/outbound/connect"
        payload = {
            'token': token,
            'u_number': re.sub(r'\D', '', sender_number),
            'c_number': to_num
        }
        headers = {}
        is_json_request = False
    
    # Mask sensitive keys for logging
    log_payload = payload.copy()
    if 'token' in log_payload: log_payload['token'] = '***'
    if 'secret_token' in log_payload: log_payload['secret_token'] = '***'
    logger.info(f"Dispatching MyOperator call to {to_num} via {url}. Payload: {log_payload}")
    
    try:
        if is_json_request:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
        else:
            response = requests.post(url, data=payload, headers=headers, timeout=10)
        
        try:
            res_data = response.json()
        except ValueError:
            res_data = {"status": "error", "message": f"Non-JSON response (Status {response.status_code}): {response.text[:100]}"}
            logger.error(f"MyOperator Non-JSON Response: {response.text}")

        # MyOperator OBD/Connect typical success status
        if res_data.get('status') == 'success' or str(res_data.get('code')) == '200':
            # sid might be in data.uuid for OBD or top level for connect
            log.sid = res_data.get('data', {}).get('uuid') or res_data.get('uuid') or res_data.get('data', {}).get('message_id')
            log.status = 'initiated'
            log.meta = {'myoperator_response': res_data}
            logger.info(f"MyOperator call initiated. SID: {log.sid}")
        else:
            log.status = 'failed'
            error_msg = res_data.get('message') or res_data.get('data', {}).get('message') or 'MyOperator API Error'
            if res_data.get('details'):
                error_msg += f" (Details: {res_data.get('details')})"
            log.error = error_msg
            logger.error(f"MyOperator API Error: {log.error}. Full Response: {res_data}")
            
    except Exception as e:
        log.status = 'failed'
        log.error = f"Dispatch Error: {str(e)}"
        logger.error(f"MyOperator dispatch exception: {e}")
        
    db.session.commit()
    return log

def send_myoperator_whatsapp(organization_id, contact_id, body, campaign_id=None, sender_number_id=None, content_sid=None, content_variables=None):
    """
    Send a WhatsApp message via MyOperator WhatsApp API.
    """
    logger.info("send_myoperator_whatsapp invoked for Org %s, Contact %s", organization_id, contact_id)
    
    log = DeliveryLog(campaign_id=campaign_id, contact_id=contact_id, channel='whatsapp_text', status='queued')
    db.session.add(log)
    db.session.commit()

    org = Organization.query.get(organization_id)
    custom_conf = org.twilio_config.get('myoperator', {}) if org and org.twilio_config else {}
    
    wa_key = custom_conf.get('wa_key')
    company_id = custom_conf.get('company_id')
    sender_number = custom_conf.get('wa_number') or custom_conf.get('number')

    if sender_number_id:
        from models.models import CommunicationNumber
        sender_record = CommunicationNumber.query.get(sender_number_id)
        if sender_record and sender_record.organization_id == organization_id and sender_record.active:
            sender_number = sender_record.number

    if not wa_key or not company_id or not sender_number:
        log.status = 'failed'
        log.error = 'MyOperator WhatsApp (Key, Company ID or Number) not configured'
        db.session.commit()
        return log

    contact = Contact.query.get(contact_id)
    if not contact:
        log.status = 'failed'
        log.error = 'Contact not found'
        db.session.commit()
        return log

    to_num = re.sub(r'\D', '', contact.phone)
    if len(to_num) == 10:
        to_num = '91' + to_num

    # MyOperator Public API for WhatsApp
    url = "https://publicapi.myoperator.co/whatsapp/send"
    
    # Payload for MyOperator WhatsApp API often looks like this
    payload = {
        'company_id': company_id,
        'to': to_num,
        'body': body,
        'from': sender_number
    }
    
    if content_sid:
        payload['template_id'] = content_sid
        if content_variables:
            payload['variables'] = content_variables

    headers = {
        'Authorization': wa_key
    }

    logger.info(f"Dispatching MyOperator WhatsApp to {to_num} via Public API")

    try:
        response = requests.post(url, data=payload, headers=headers, timeout=10)
        
        try:
            res_data = response.json()
        except ValueError:
            res_data = {"status": "error", "message": f"Non-JSON response (Status {response.status_code}): {response.text[:100]}"}
            logger.error(f"MyOperator WA Non-JSON Response: {response.text}")

        if res_data.get('status') == 'success' or res_data.get('code') == 200:
            log.sid = res_data.get('data', {}).get('message_id') or res_data.get('message_id')
            log.status = 'sent'
            log.meta = {'myoperator_msg_id': log.sid}
            logger.info(f"MyOperator WhatsApp sent. ID: {log.sid}")
        else:
            log.status = 'failed'
            log.error = res_data.get('message', 'MyOperator WhatsApp API Error')
            logger.error(f"MyOperator WhatsApp Error: {log.error}")
            
    except Exception as e:
        log.status = 'failed'
        log.error = f"Dispatch Error: {str(e)}"
        logger.error(f"MyOperator WhatsApp exception: {e}")
        
    db.session.commit()
    return log
