import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from app.extensions import db
from app.models import (Campaign, CampaignTarget, DeliveryLog,
                        ModuleGroup, Script, ModuleRecord,
                        Organization, CallTargetResult)
from app.services.humanlab_provider import HumanLabProvider
from app.common.notifications.twilio import (
    send_whatsapp_text,
    send_whatsapp_bundle,
    resolve_whatsapp_sender,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# STATUS CONSTANTS
# ──────────────────────────────────────────────────────────────
TERMINAL_STATUSES = {"answered", "completed", "failed", "partial_success"}

RETRY_DELAY_SECONDS = 300   # 5 minutes

_PHONE_KEYS = [
    "phone", "number", "phone_number", "phonenumber",
    "mobile", "mobile_number", "contact", "telephone",
    "tel", "cell", "whatsapp", "contact_number",
]

def _extract_phone_from_record(record):
    """Return the phone number string from a ModuleRecord, or None."""
    for rv in record.values:
        if rv.field and rv.field.field_type and rv.field.field_type.lower() == "phone":
            if rv.value:
                return str(rv.value).strip()
    cleaned = {k.strip().lower(): v for k, v in record.named_values.items()}
    for key in _PHONE_KEYS:
        val = cleaned.get(key)
        if val:
            return str(val).strip()
    return None


class CampaignExecutionService:

    # ══════════════════════════════════════════════════════════════
    # 1. EXECUTE CALL
    #    Accepted statuses: queued | retrying
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _execute_call(app, campaign_id, target_id, phone, script_text, language):
        logger.info(f"[CALL START] [target={target_id}] phone={phone}")
        with app.app_context():
            campaign = db.session.get(Campaign, campaign_id)
            target   = db.session.get(CampaignTarget, target_id)

            if not target:
                logger.error(f"[CALL START] [target={target_id}] NOT FOUND — abort")
                return
            if target.status not in ("queued", "retrying"):
                logger.warning(f"[CALL START] [target={target_id}] status='{target.status}' — skip")
                return
            if not campaign or campaign.status != "running":
                logger.warning(f"[CALL START] [target={target_id}] campaign not running — abort")
                return

            # Mark calling
            target.status = "calling"
            target.call_attempts += 1
            target.last_attempt_at = datetime.utcnow()
            target.next_retry_at   = None
            db.session.commit()

            # Determine provider based on sender_number_id
            provider = "hooman_labs" # default
            if campaign.sender_number_id:
                from app.models import CommunicationNumber
                sender_number_record = db.session.get(CommunicationNumber, campaign.sender_number_id)
                if sender_number_record:
                    if sender_number_record.channel_type and sender_number_record.channel_type.lower() == "voice":
                        provider = "twilio"
                    elif sender_number_record.channel_type and sender_number_record.channel_type.lower() == "hooman_voice":
                        provider = "hooman_labs"

            if provider == "hooman_labs":
                # Call Hooman Labs
                result = HumanLabProvider.start_call(
                    {"campaign_id": campaign_id, "phone": phone,
                     "script": script_text, "language": language},
                    campaign.organization_id
                )
                success  = result.get("success", False)
                task_id  = result.get("task_id", "")
                logger.info(f"[CALL START] [target={target_id}] Hooman result: success={success}, task_id={task_id}")
                from app.core.logging_system import log_activity
                log_activity("CALL_DISPATCH", f"Target {target_id} phone={phone}, success={success}, task_id={task_id}")
    
                # Normalize recipient to last-10 digits for consistent LIKE matching
                import re as _re_r
                _r = _re_r.sub(r'\D', '', phone)
                if _r.startswith('91') and len(_r) == 12:
                    _r = _r[2:]
                elif len(_r) > 10:
                    _r = _r[-10:]
                _recipient = _r if _r else phone
    
                # DeliveryLog
                log = DeliveryLog(
                    organization_id=campaign.organization_id,
                    campaign_id=campaign_id,
                    record_id=target.record_id,
                    channel="hooman_voice",
                    recipient=_recipient,
                    status="waiting_webhook" if success else "failed",
                    error=result.get("error"),
                    sid=task_id,
                    meta={"language": language, "attempt": target.call_attempts,
                          "provider": "hooman_labs", "webhook_received": False}
                )
                db.session.add(log)
    
                if success:
                    target.status = "waiting_webhook"
                    target.conversation_id = task_id
                    target.external_task_id = task_id
                    target.last_call_status = "waiting_webhook"
                else:
                    # Immediate failure — treat like a no-answer webhook
                    target.status = "failed"
                    target.last_call_status = "failed"
                    target.end_reason = result.get("error", "API call failed")
                    target.completed_at = datetime.utcnow()
    
                db.session.commit()
    
                if not success:
                    # Decide retry or fallback right now
                    CampaignExecutionService._handle_no_answer(app, target_id)
            else:
                # Call Twilio
                from app.common.notifications.twilio import make_call
                
                log = make_call(
                    organization_id=campaign.organization_id,
                    contact_id=target.contact_id,
                    tts_text=script_text,
                    language=language,
                    campaign_id=campaign_id,
                    sender_number_id=campaign.sender_number_id,
                    phone=phone,
                    record_id=target.record_id
                )
                
                # Target status updates will be handled by webhook (voice-status)
                # But we can mark it as waiting_webhook for consistency
                if log.status != "failed":
                    target.status = "waiting_webhook"
                    target.last_call_status = "waiting_webhook"
                else:
                    target.status = "failed"
                    target.last_call_status = "failed"
                    target.end_reason = log.error or "Twilio API call failed"
                    target.completed_at = datetime.utcnow()
                db.session.commit()
                
                if log.status == "failed":
                    CampaignExecutionService._handle_no_answer(app, target_id)

    # ══════════════════════════════════════════════════════════════
    # 1.5. EXECUTE WHATSAPP CAMPAIGN (TEXT + optional VOICE NOTE)
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _execute_whatsapp_campaign(app, campaign_id, target_id, phone, script_text, language="English"):
        logger.info(f"[WHATSAPP START] [target={target_id}] phone={phone}")
        with app.app_context():
            campaign = db.session.get(Campaign, campaign_id)
            target   = db.session.get(CampaignTarget, target_id)

            if not target:
                logger.error(f"[WHATSAPP START] [target={target_id}] NOT FOUND — abort")
                return
            if target.status not in ("queued", "retrying"):
                logger.warning(
                    f"[WHATSAPP START] [target={target_id}] "
                    f"status='{target.status}' — skip"
                )
                return
            if not campaign or campaign.status != "running":
                logger.warning(
                    f"[WHATSAPP START] [target={target_id}] campaign not running — abort"
                )
                return

            record = db.session.get(ModuleRecord, target.record_id)
            script = db.session.get(Script, campaign.script_id)

            # Mark as sending attempt (not terminal yet)
            target.call_attempts += 1
            target.last_attempt_at = datetime.utcnow()
            target.status = "calling"   # transient — will be overwritten below
            db.session.commit()

            # ── Build message / content SID ───────────────────────
            msg_body = script_text
            content_sid = None
            content_variables = None

            if msg_body and msg_body.startswith('HX'):
                content_sid = msg_body.strip()
                import json
                values = dict(record.named_values) if record else {}
                str_values = {
                    str(k).strip(): str(v)
                    for k, v in values.items()
                    if str(k).strip().isdigit()
                }
                content_variables = json.dumps(str_values)
                msg_body = None

            # ── Voice note is ON by default for all WhatsApp campaigns ──
            # To disable: set script.voice_note_enabled = False
            voice_disabled = (
                script
                and getattr(script, 'voice_note_enabled', None) is False
            )
            voice_enabled = not voice_disabled
            voice_gender = getattr(script, 'voice_gender', 'female') or 'female'

            if voice_enabled:
                # ━━ BUNDLE: TEXT + VOICE NOTE ━━━━━━━━━━━━━━━━━━━━━
                logger.info(
                    f"[WHATSAPP BUNDLE] [target={target_id}] "
                    f"voice_note=ON  lang={language} gender={voice_gender}"
                )
                text_ok, text_sid, audio_ok, audio_sid, error = send_whatsapp_bundle(
                    organization_id=campaign.organization_id,
                    to_number=phone,
                    body=msg_body,
                    campaign_id=campaign_id,
                    target_id=target_id,
                    language=language,
                    gender=voice_gender,
                    content_sid=content_sid,
                    content_variables=content_variables,
                    record_id=record.id if record else None,
                    sender_number_id=getattr(campaign, 'sender_number_id', None),
                )

                # Re-fetch target after blocking send
                target = db.session.get(CampaignTarget, target_id)

                # Store SIDs
                target.whatsapp_text_sid = text_sid
                target.voice_sid         = audio_sid
                target.conversation_id   = text_sid or audio_sid

                if text_ok and audio_ok:
                    # ── BOTH delivered ─────────────────────────────
                    target.status           = "completed"
                    target.whatsapp_sent    = True
                    target.voice_sent       = True
                    target.voice_status     = "sent"
                    target.completed_at     = datetime.utcnow()
                    target.last_call_status = "whatsapp_bundle_sent"
                    db.session.commit()
                    logger.info(
                        f"[WHATSAPP BUNDLE SENT] [target={target_id}] "
                        f"text_sid={text_sid} audio_sid={audio_sid}"
                    )
                elif text_ok and not audio_ok:
                    # ── Text OK, audio failed → partial_success ────
                    target.status           = "partial_success"
                    target.whatsapp_sent    = True
                    target.voice_sent       = False
                    target.voice_status     = "failed"
                    target.completed_at     = datetime.utcnow()
                    target.last_call_status = "whatsapp_text_only"
                    target.end_reason       = error or "Voice note failed"
                    db.session.commit()
                    logger.warning(
                        f"[WHATSAPP PARTIAL] [target={target_id}] "
                        f"text OK, audio FAILED: {error}"
                    )
                else:
                    # ── Both failed or text failed ────────────────
                    target.status           = "failed"
                    target.whatsapp_sent    = False
                    target.voice_sent       = False
                    target.voice_status     = "failed"
                    target.completed_at     = datetime.utcnow()
                    target.end_reason       = error or "WhatsApp bundle send failed"
                    db.session.commit()
                    logger.error(
                        f"[WHATSAPP FAILED] [target={target_id}] "
                        f"error='{error}' to={phone}"
                    )
            else:
                # ━━ TEXT ONLY (original flow) ━━━━━━━━━━━━━━━━━━━━━
                success, sid, error = send_whatsapp_text(
                    organization_id=campaign.organization_id,
                    to_number=phone,
                    body=msg_body,
                    content_sid=content_sid,
                    content_variables=content_variables,
                    record_id=record.id if record else None,
                    sender_number_id=getattr(campaign, 'sender_number_id', None),
                    campaign_id=campaign_id
                )

                # Re-fetch target after blocking send
                target = db.session.get(CampaignTarget, target_id)

                if success and sid:
                    target.status           = "completed"
                    target.whatsapp_sent    = True
                    target.completed_at     = datetime.utcnow()
                    target.last_call_status = "whatsapp_sent"
                    target.conversation_id  = sid
                    target.whatsapp_text_sid = sid
                    db.session.commit()
                    logger.info(
                        f"[WHATSAPP CAMPAIGN SENT] [target={target_id}] "
                        f"sid={sid} to={phone}"
                    )
                else:
                    target.status           = "failed"
                    target.whatsapp_sent    = False
                    target.completed_at     = datetime.utcnow()
                    target.end_reason       = error or "WhatsApp send failed"
                    db.session.commit()
                    logger.error(
                        f"[WHATSAPP FAILED] [target={target_id}] "
                        f"error='{error}' to={phone}"
                    )

            CampaignExecutionService._check_campaign_completion(app, campaign_id)



    # ══════════════════════════════════════════════════════════════
    # 2. WEBHOOK HANDLER
    #    Single entry point for all Hooman Labs webhooks.
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def handle_webhook(app, webhook_data):
        """
        Process a Hooman Labs webhook for EXACTLY ONE target.
        Matching priority: conversation_id → phone (recipient).
        """
        with app.app_context():
            call_info      = webhook_data.get("callInfo", {}) or {}
            conversation_id = (
                webhook_data.get("conversationId")
                or call_info.get("task")
                or call_info.get("callSid")
                or webhook_data.get("taskId")
                or webhook_data.get("CallUUID")
                or webhook_data.get("call_uuid")
                or webhook_data.get("call_id")
                or webhook_data.get("task_id")
                or webhook_data.get("sid")
                or webhook_data.get("id")
                or ""
            )
            connected      = webhook_data.get("connected", False)
            duration       = webhook_data.get("duration", 0)
            outcome        = (webhook_data.get("outcome") or "").lower()
            end_reason     = (webhook_data.get("endReason") or "").lower()
            task_completed = webhook_data.get("taskCompleted", False)
            attempt        = webhook_data.get("attempt", 1)
            summary        = webhook_data.get("summary", "")
            transcript     = webhook_data.get("transcript", "")
            call_to        = call_info.get("to", "")

            logger.info(
                f"[WEBHOOK RECEIVED] conversationId={conversation_id} "
                f"connected={connected} outcome={outcome} endReason={end_reason}"
            )

            # ── Find DeliveryLog and CampaignTarget ──
            target = None
            log = None

            w_conv_id = webhook_data.get("conversationId") or ""
            w_task_id = webhook_data.get("taskId") or call_info.get("task") or ""
            w_phone = call_to or webhook_data.get("phone") or ""

            # Normalize phone once
            import re as _re
            n_phone = ""
            if w_phone:
                n_phone = _re.sub(r'\D', '', w_phone)
                if n_phone.startswith('91') and len(n_phone) == 12:
                    n_phone = n_phone[2:]
                elif len(n_phone) > 10:
                    n_phone = n_phone[-10:]

            # 1. By conversationId
            if w_conv_id:
                target = CampaignTarget.query.filter(
                    (CampaignTarget.conversation_id == w_conv_id) |
                    (CampaignTarget.external_task_id == w_conv_id)
                ).first()
                if not target:
                    log = DeliveryLog.query.filter_by(sid=w_conv_id).first()

            # 2. By taskId
            if not target and not log and w_task_id:
                target = CampaignTarget.query.filter(
                    (CampaignTarget.conversation_id == w_task_id) |
                    (CampaignTarget.external_task_id == w_task_id)
                ).first()
                if not target:
                    log = DeliveryLog.query.filter_by(sid=w_task_id).first()

            # 3. By normalized phone — prefer active-status hooman_voice logs
            if not target and not log and n_phone:
                log = DeliveryLog.query.filter(
                    DeliveryLog.channel == "hooman_voice",
                    DeliveryLog.status.in_(["waiting_webhook", "in-progress", "ringing"]),
                    DeliveryLog.recipient.like(f"%{n_phone}")
                ).order_by(DeliveryLog.created_at.desc()).first()

                if not log:
                    log = DeliveryLog.query.filter(
                        DeliveryLog.channel == "hooman_voice",
                        DeliveryLog.recipient.like(f"%{n_phone}")
                    ).order_by(DeliveryLog.created_at.desc()).first()

            # 4. Cross-link
            if target and not log:
                log = DeliveryLog.query.filter_by(
                    campaign_id=target.campaign_id,
                    record_id=target.record_id
                ).order_by(DeliveryLog.created_at.desc()).first()
            elif log and not target:
                target = CampaignTarget.query.filter_by(
                    campaign_id=log.campaign_id,
                    record_id=log.record_id
                ).filter(
                    CampaignTarget.status.in_(
                        ["calling", "waiting_webhook", "retrying"]
                    )
                ).order_by(CampaignTarget.id.desc()).first()

                if not target:
                    target = CampaignTarget.query.filter_by(
                        campaign_id=log.campaign_id,
                        record_id=log.record_id
                    ).order_by(CampaignTarget.id.desc()).first()

            # 5. Bind new conversationId to target so next webhooks match instantly
            if target and w_conv_id and target.conversation_id != w_conv_id:
                target.conversation_id = w_conv_id
                db.session.commit()
                logger.info(
                    f"[WEBHOOK RECEIVED] [target={target.id}] "
                    f"Bound conversationId={w_conv_id} (was={target.conversation_id})"
                )

            if not log:
                logger.warning(
                    f"[WEBHOOK RECEIVED] No DeliveryLog for "
                    f"conversationId={w_conv_id} to={call_to}. Raw webhook: {webhook_data}"
                )
                return False

            if not target:
                logger.warning(f"[WEBHOOK RECEIVED] No CampaignTarget for log.id={log.id}")
                return False

            logger.info(f"[WEBHOOK RECEIVED] [target={target.id}] matched")

            # ── Safety: skip if already terminal ──
            if target.status in TERMINAL_STATUSES:
                logger.info(
                    f"[WEBHOOK RECEIVED] [target={target.id}] "
                    f"already terminal ({target.status}) — skip"
                )
                return True

            # ── Update DeliveryLog meta ──
            from sqlalchemy.orm.attributes import flag_modified
            log.meta = {
                **(log.meta or {}),
                "webhook_received": True,
                "webhook_received_at": datetime.utcnow().isoformat(),
                "connected": connected, "duration_seconds": duration,
                "outcome": outcome, "end_reason": end_reason,
                "task_completed": task_completed,
            }
            flag_modified(log, "meta")

            # ── Update target shared fields ──
            target.connected       = connected
            target.duration        = duration
            target.end_reason      = end_reason
            target.attempt         = attempt
            target.summary         = summary
            target.transcript      = transcript
            target.conversation_id = conversation_id
            target.last_webhook_at = datetime.utcnow()

            FAILURE_REASONS = {
                "failed", "busy", "no_answer", "no-answer",
                "error", "rejected", "canceled", "not_answered"
            }
            is_answered = (
                connected
                or task_completed
                or outcome == "completed"
                or log.status in ["completed", "answered"]
            )
            is_failed = (
                end_reason in FAILURE_REASONS
                or outcome in FAILURE_REASONS
                or log.status in FAILURE_REASONS
                or log.status == "no-answer"
                or log.status == "failed"
            )

            # ── Record CallTargetResult ──
            ctr = CallTargetResult(
                target_id=target.id,
                attempt_number=target.call_attempts,
                connected=connected, duration=duration,
                outcome=outcome, end_reason=end_reason,
                transcript=transcript, summary=summary,
                conversation_id=conversation_id
            )
            db.session.add(ctr)

            if is_answered:
                target.status = "answered"
                target.last_call_status = "answered"
                target.completed_at = datetime.utcnow()
                log.status = "answered"
                logger.info(f"[TARGET COMPLETED] [target={target.id}] -> answered")
                db.session.commit()
                CampaignExecutionService._check_campaign_completion(
                    app, log.campaign_id
                )

            elif is_failed:
                log.status = "failed"
                db.session.commit()
                logger.info(
                    f"[WEBHOOK RECEIVED] [target={target.id}] "
                    f"not answered — checking retry"
                )
                CampaignExecutionService._handle_no_answer(app, target.id)

            else:
                # Intermediate webhook (ringing / in-progress) — keep waiting
                log.status = "in-progress"
                db.session.commit()
                logger.info(
                    f"[WEBHOOK RECEIVED] [target={target.id}] "
                    f"intermediate — still waiting"
                )

            return True

    # ══════════════════════════════════════════════════════════════
    # 3. HANDLE NO-ANSWER (called by webhook + watchdog + execute)
    #    Decides: schedule retry OR send WhatsApp.
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _handle_no_answer(app, target_id):
        with app.app_context():
            target = db.session.get(CampaignTarget, target_id)
            if not target:
                return
            # Safety: don't touch already-terminal targets
            if target.status in TERMINAL_STATUSES:
                logger.info(
                    f"[HANDLE NO-ANSWER] [target={target_id}] "
                    f"already {target.status} — skip"
                )
                return

            campaign = db.session.get(Campaign, target.campaign_id)
            if not campaign or campaign.status != "running":
                return

            max_retries = campaign.max_retry if campaign.max_retry is not None else 1

            if target.retry_count < max_retries:
                # ── Schedule retry ──
                target.retry_count  += 1
                target.status        = "retry_pending"
                target.next_retry_at = datetime.utcnow() + timedelta(seconds=RETRY_DELAY_SECONDS)
                db.session.commit()
                logger.info(
                    f"[RETRY SCHEDULED] [target={target_id}] "
                    f"retry_at={target.next_retry_at.isoformat()} "
                    f"(retry {target.retry_count}/{max_retries})"
                )
                # Timer fires the actual retry
                threading.Timer(
                    RETRY_DELAY_SECONDS,
                    CampaignExecutionService._fire_retry,
                    args=(app, target_id)
                ).start()
            else:
                # ── Max retries exhausted — WhatsApp fallback ──
                script = db.session.get(Script, campaign.script_id)
                record = db.session.get(ModuleRecord, target.record_id)
                phone  = _extract_phone_from_record(record) if record else None

                if script and script.backup_enabled and phone:
                    logger.info(
                        f"[WHATSAPP START] [target={target_id}] "
                        f"voice fallback — sending to {phone}"
                    )
                    # Run synchronously in the same thread — result updates target directly
                    threading.Thread(
                        target=CampaignExecutionService._send_whatsapp_message,
                        args=(app, campaign.id, target_id, phone),
                        daemon=True
                    ).start()
                else:
                    target.status       = "failed"
                    target.completed_at  = datetime.utcnow()
                    db.session.commit()
                    logger.warning(
                        f"[TARGET COMPLETED] [target={target_id}] -> failed "
                        f"(no WhatsApp backup)"
                    )
                    CampaignExecutionService._check_campaign_completion(
                        app, campaign.id
                    )

    # ══════════════════════════════════════════════════════════════
    # 4. FIRE RETRY — called by Timer after 5 min
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _fire_retry(app, target_id):
        logger.info(f"[RETRY EXECUTION] [target={target_id}] timer fired")
        with app.app_context():
            target = db.session.get(CampaignTarget, target_id)
            if not target:
                logger.error(f"[RETRY EXECUTION] [target={target_id}] NOT FOUND")
                return
            # Safety guard
            if target.status in TERMINAL_STATUSES:
                logger.warning(
                    f"[RETRY EXECUTION] [target={target_id}] "
                    f"already {target.status} — skip"
                )
                return
            if target.status != "retry_pending":
                logger.warning(
                    f"[RETRY EXECUTION] [target={target_id}] "
                    f"status='{target.status}' not retry_pending — skip"
                )
                return

            campaign = db.session.get(Campaign, target.campaign_id)
            if not campaign or campaign.status != "running":
                logger.warning(
                    f"[RETRY EXECUTION] [target={target_id}] campaign not running"
                )
                return

            script = db.session.get(Script, campaign.script_id)
            record = db.session.get(ModuleRecord, target.record_id)
            if not script or not record:
                logger.error(
                    f"[RETRY EXECUTION] [target={target_id}] "
                    f"missing script/record"
                )
                target.status = "failed"
                target.completed_at = datetime.utcnow()
                db.session.commit()
                CampaignExecutionService._check_campaign_completion(app, campaign.id)
                return

            phone = _extract_phone_from_record(record)
            if not phone:
                logger.error(
                    f"[RETRY EXECUTION] [target={target_id}] no phone — fail"
                )
                target.status = "failed"
                target.completed_at = datetime.utcnow()
                db.session.commit()
                CampaignExecutionService._check_campaign_completion(app, campaign.id)
                return

            # Build script text
            script_text = script.content
            for key, val in record.named_values.items():
                k = key.strip()
                script_text = script_text.replace(f"{{{{{k}}}}}", str(val))
                script_text = script_text.replace(f"{{{k}}}", str(val))

            language = script.language or "English"

            # Mark retrying BEFORE spawning thread
            target.status = "retrying"
            db.session.commit()
            logger.info(
                f"[RETRY EXECUTION] [target={target_id}] "
                f"firing call to {phone}"
            )

            threading.Thread(
                target=CampaignExecutionService._execute_call,
                args=(app, campaign.id, target_id, phone, script_text, language),
                daemon=True
            ).start()

    # ══════════════════════════════════════════════════════════════
    # 5. WHATSAPP FALLBACK
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _send_whatsapp_message(app, campaign_id, target_id, phone):
        """
        Voice-call fallback: send WhatsApp TEXT + MP3 after max retries exhausted.

        Flow:
          1. [FALLBACK START]   — load campaign/script/record
          2. [SENDER RESOLVED] — validate WhatsApp sender (never uses call number)
          3. send_whatsapp_bundle() — TEXT first, MP3 only if text succeeds
          4. [TEXT SENT] / [MP3 SENT] / [FALLBACK COMPLETE]

        On any failure: status='fallback_failed', completed=True, no infinite retry.
        """
        logger.info("[FALLBACK START] [target=%s] to=%s", target_id, phone)
        with app.app_context():
            campaign = db.session.get(Campaign, campaign_id)
            target   = db.session.get(CampaignTarget, target_id)

            if not campaign or not target:
                logger.error(
                    "[FALLBACK START] [target=%s] campaign or target not found — abort",
                    target_id
                )
                return

            script = db.session.get(Script, campaign.script_id)
            record = db.session.get(ModuleRecord, target.record_id)

            # ── Guard: backup must be configured ───────────────────
            if not script or not script.backup_enabled or not script.backup_template:
                clean_error = "No WhatsApp backup template configured"
                logger.warning(
                    "[CALL RETRY FAILED] [target=%s] %s", target_id, clean_error
                )
                target.status       = "fallback_failed"
                target.completed_at = datetime.utcnow()
                target.end_reason   = clean_error
                db.session.commit()
                CampaignExecutionService._check_campaign_completion(app, campaign_id)
                return

            # ── Pre-validate WhatsApp sender ───────────────────────
            # resolve_whatsapp_sender() ONLY looks at org's WhatsApp config / env.
            # It NEVER falls through to a voice/call sender — this is what caused
            # Twilio Error 63007 in the old code.
            try:
                resolved_client, resolved_sender = resolve_whatsapp_sender(
                    campaign.organization_id
                )
                logger.info(
                    "[SENDER RESOLVED] [target=%s] org=%s sender=%s",
                    target_id, campaign.organization_id, resolved_sender
                )
            except ValueError as sender_err:
                clean_error = str(sender_err)[:90]
                logger.error(
                    "[CALL RETRY FAILED] [target=%s] sender_not_configured — %s",
                    target_id, clean_error
                )
                target.status       = "fallback_failed"
                target.completed_at = datetime.utcnow()
                target.end_reason   = "sender_not_configured: " + clean_error
                db.session.commit()
                CampaignExecutionService._check_campaign_completion(app, campaign_id)
                return

            # ── Build message body ─────────────────────────────────
            values = dict(record.named_values) if record else {}
            org    = db.session.get(Organization, campaign.organization_id)
            values["campaign"]     = campaign.name
            values["number"]       = phone
            values["organization"] = org.name if org else ""

            msg_body    = script.backup_template.strip() if script.backup_template else ""
            content_sid = None
            content_variables = None

            if msg_body and msg_body.startswith('HX'):
                content_sid = msg_body.strip()
                import json
                str_values = {
                    str(k).strip(): str(v)
                    for k, v in values.items()
                    if str(k).strip().isdigit()
                }
                content_variables = json.dumps(str_values)
                msg_body = None
            else:
                import re as _re
                for k, v in values.items():
                    ck = k.strip()
                    msg_body = _re.sub(
                        r"\{\{" + _re.escape(ck) + r"\}\}",
                        str(v), msg_body, flags=_re.IGNORECASE
                    )
                    msg_body = _re.sub(
                        r"\{" + _re.escape(ck) + r"\}",
                        str(v), msg_body, flags=_re.IGNORECASE
                    )

            language     = script.language or "English"
            voice_gender = getattr(script, 'voice_gender', 'female') or 'female'

            logger.info(
                "[FALLBACK START] [target=%s] sending bundle — lang=%s gender=%s",
                target_id, language, voice_gender
            )

            # ── Send bundle: TEXT first, MP3 only if text succeeded ─
            # sender_number_id=None forces send_whatsapp_bundle to use the
            # WhatsApp-specific org config / env (same path as direct campaigns).
            # Passing the campaign's sender_number_id would hand a CALL number
            # to Twilio → Error 63007.
            text_ok, text_sid, audio_ok, audio_sid, error = send_whatsapp_bundle(
                organization_id=campaign.organization_id,
                to_number=phone,
                body=msg_body,
                campaign_id=campaign_id,
                target_id=target_id,
                language=language,
                gender=voice_gender,
                content_sid=content_sid,
                content_variables=content_variables,
                record_id=record.id if record else None,
                sender_number_id=None,   # MUST be None — never use the call number
            )

            # Re-fetch after blocking bundle send
            target = db.session.get(CampaignTarget, target_id)

            # ── Evaluate result ────────────────────────────────────
            if not text_ok:
                # TEXT failed — stop immediately, do NOT generate/send MP3
                clean_error = str(error)[:90] if error else "WhatsApp text send failed"
                logger.error(
                    "[CALL RETRY FAILED] [target=%s] TEXT failed — %s",
                    target_id, clean_error
                )
                target.status         = "fallback_failed"
                target.whatsapp_sent  = False
                target.completed_at   = datetime.utcnow()
                target.end_reason     = clean_error
                db.session.commit()
                logger.info("[FALLBACK COMPLETE] [target=%s] failed (text)", target_id)
                CampaignExecutionService._check_campaign_completion(app, campaign_id)
                return

            # Text succeeded
            logger.info(
                "[TEXT SENT] [target=%s] sid=%s to=%s", target_id, text_sid, phone
            )
            target.whatsapp_text_sid = text_sid

            if audio_ok:
                logger.info(
                    "[MP3 SENT] [target=%s] sid=%s", target_id, audio_sid
                )
                target.voice_sid    = audio_sid
                target.voice_sent   = True
                target.voice_status = "sent"
            else:
                audio_err = str(error)[:90] if error else "MP3 send failed"
                logger.warning(
                    "[MP3 FAILED] [target=%s] %s — text was delivered, marking partial",
                    target_id, audio_err
                )
                target.voice_sent   = False
                target.voice_status = "failed"
                target.end_reason   = audio_err

            # Mark completed (text delivered = success; audio optional)
            target.status           = "completed"
            target.whatsapp_sent    = True
            target.completed_at     = datetime.utcnow()
            target.last_call_status = "whatsapp_fallback_sent"
            target.conversation_id  = text_sid or audio_sid
            db.session.commit()
            logger.info(
                "[WHATSAPP SENT] [target=%s] text_sid=%s audio_sid=%s to=%s",
                target_id, text_sid, audio_sid, phone
            )
            logger.info("[FALLBACK COMPLETE] [target=%s] success", target_id)

            CampaignExecutionService._check_campaign_completion(app, campaign_id)

    # Keep old name as alias for __init__.py send_whatsapp calls
    @staticmethod
    def send_whatsapp(app, campaign_id, target_id, phone):
        CampaignExecutionService._send_whatsapp_message(
            app, campaign_id, target_id, phone
        )

    # ══════════════════════════════════════════════════════════════
    # 6. WATCHDOG — handles stuck waiting_webhook targets
    #    Called from __init__.py background thread every 2 min
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _handle_stuck_target(app, target_id):
        """Target was in waiting_webhook for > 5 min with no webhook arriving."""
        with app.app_context():
            target = db.session.get(CampaignTarget, target_id)
            if not target:
                return
            if target.status in TERMINAL_STATUSES:
                logger.info(
                    f"[WATCHDOG] [target={target_id}] "
                    f"already {target.status} — skip"
                )
                return
            if target.status != "waiting_webhook":
                logger.warning(
                    f"[WATCHDOG] [target={target_id}] "
                    f"status='{target.status}' — skip"
                )
                return

            campaign = db.session.get(Campaign, target.campaign_id)
            if not campaign or campaign.status != "running":
                return

            logger.info(
                f"[WATCHDOG] [target={target_id}] "
                f"stuck in waiting_webhook — treating as no-answer"
            )
            # Treat exactly like a no-answer webhook
            CampaignExecutionService._handle_no_answer(app, target_id)

    # ══════════════════════════════════════════════════════════════
    # 7. CAMPAIGN COMPLETION CHECK
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _check_campaign_completion(app, campaign_id):
        with app.app_context():
            campaign = db.session.get(Campaign, campaign_id)
            if not campaign or campaign.status != "running":
                return

            total = CampaignTarget.query.filter_by(
                campaign_id=campaign_id
            ).count()

            done = CampaignTarget.query.filter(
                CampaignTarget.campaign_id == campaign_id,
                CampaignTarget.status.in_(
                    ["answered", "completed", "failed"]
                )
            ).count()

            remaining = total - done
            logger.info(
                f"[CAMPAIGN COMPLETED] Campaign {campaign_id}: "
                f"total={total} done={done} remaining={remaining}"
            )

            if remaining == 0 and total > 0:
                failed_count = CampaignTarget.query.filter_by(
                    campaign_id=campaign_id, status="failed"
                ).count()
                campaign.status = "failed" if failed_count == total else "completed"
                db.session.commit()
                
                # Release Campaign Express number if assigned
                if getattr(campaign, 'campaign_express_user_id', None):
                    from app.services.ce_number_allocator import CeNumberAllocator
                    CeNumberAllocator.release(campaign_id)
                
                logger.info(
                    f"[CAMPAIGN COMPLETED] Campaign {campaign_id} -> "
                    f"{campaign.status}"
                )

    # ══════════════════════════════════════════════════════════════
    # 8. PROCESS QUEUE — initial call blast
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _process_queue(app, campaign_id):
        logger.info(
            f"[CALL START] _process_queue starting for campaign {campaign_id}"
        )
        try:
            with app.app_context():
                campaign = db.session.get(Campaign, campaign_id)
                if not campaign or campaign.status != "running":
                    return

                if getattr(campaign, 'campaign_express_user_id', None):
                    from app.services.ce_number_allocator import CeNumberAllocator
                    allocated_number = CeNumberAllocator.allocate(campaign_id)
                    if not allocated_number:
                        logger.error(f"[CE ALLOCATOR] No numbers available for CE campaign {campaign_id}")
                        campaign.status = "failed"
                        db.session.commit()
                        return

                script = db.session.get(Script, campaign.script_id)
                if not script:
                    campaign.status = "failed"
                    db.session.commit()
                    return

                group = db.session.get(ModuleGroup, campaign.group_id)
                if not group or not group.records:
                    campaign.status = "failed"
                    db.session.commit()
                    return

                # Create targets for all records (first time only)
                for record in group.records:
                    existing = CampaignTarget.query.filter_by(
                        campaign_id=campaign_id,
                        record_id=record.id
                    ).first()
                    if not existing:
                        db.session.add(CampaignTarget(
                            campaign_id=campaign_id,
                            record_id=record.id,
                            status="queued",
                            call_attempts=0,
                            retry_count=0
                        ))
                db.session.commit()

                # Fetch ONLY queued targets — never retry_pending/retrying
                targets = CampaignTarget.query.filter_by(
                    campaign_id=campaign_id, status="queued"
                ).all()
                logger.info(
                    f"[CALL START] Campaign {campaign_id}: "
                    f"submitting {len(targets)} queued targets"
                )
                language = script.language or "English"

                with ThreadPoolExecutor(max_workers=5) as executor:
                    for target in targets:
                        db.session.refresh(campaign)
                        if campaign.status != "running":
                            break
                        record = db.session.get(ModuleRecord, target.record_id)
                        if not record:
                            continue
                        phone = _extract_phone_from_record(record)
                        if not phone:
                            target.status = "failed"
                            target.completed_at = datetime.utcnow()
                            db.session.commit()
                            continue

                        # ── Build substitution context ───────────────────
                        import re as _re
                        values = dict(record.named_values)
                        org = db.session.get(Organization, campaign.organization_id)
                        # Add useful built-in variables
                        values.setdefault("campaign", campaign.name)
                        values.setdefault("number",   phone)
                        values.setdefault("organization", org.name if org else "")

                        script_text = script.content
                        for k, v in values.items():
                            ck = k.strip()
                            # Case-insensitive match: {{Name}} == {{name}} == {{NAME}}
                            script_text = _re.sub(
                                r"\{\{" + _re.escape(ck) + r"\}\}",
                                str(v),
                                script_text,
                                flags=_re.IGNORECASE,
                            )
                            # Also handle single-brace {Name}
                            script_text = _re.sub(
                                r"\{" + _re.escape(ck) + r"\}",
                                str(v),
                                script_text,
                                flags=_re.IGNORECASE,
                            )

                        if campaign.type == 'call':
                            executor.submit(
                                CampaignExecutionService._execute_call,
                                app, campaign_id, target.id,
                                phone, script_text, language
                            )
                        elif campaign.type == 'whatsapp_text':
                            executor.submit(
                                CampaignExecutionService._execute_whatsapp_campaign,
                                app, campaign_id, target.id,
                                phone, script_text, language
                            )
                        else:
                            logger.warning(f"[CALL START] Campaign {campaign_id}: unknown type {campaign.type}")
                            target.status = "failed"
                            target.end_reason = f"Unknown campaign type: {campaign.type}"
                            target.completed_at = datetime.utcnow()
                            db.session.commit()

                logger.info(
                    f"[CALL START] Campaign {campaign_id}: "
                    f"all calls submitted — waiting for webhooks"
                )

        except Exception as e:
            import traceback
            logger.error(
                f"[CALL START] _process_queue EXCEPTION: {e}\n"
                f"{traceback.format_exc()}"
            )

    # ══════════════════════════════════════════════════════════════
    # 9. START — public entry point
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def start(campaign_id):
        from flask import current_app
        app = current_app._get_current_object()
        threading.Thread(
            target=CampaignExecutionService._process_queue,
            args=(app, campaign_id),
            daemon=True
        ).start()

    # kept for backward compat
    @staticmethod
    def start_watchdog(app):
        pass
