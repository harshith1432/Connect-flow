# ConnectFlow API Reference

ConnectFlow provides a robust REST API for managing external interactions and handling internal dynamic component updates.

## Authentication
Most endpoints require an active session and a CSRF token. Cross-Origin requests and third-party integrations (like Twilio Webhooks) authenticate using API Key validation or specialized payload signatures.

## Module Management (Dynamic CRM)

### `GET /api/modules/<mid>/fields`
Fetches the dynamically configured fields for a given module.
**Response:**
```json
{
  "fields": [
    {"name": "Email", "type": "email", "required": true},
    {"name": "Status", "type": "select", "options": ["Pending", "Active"]}
  ]
}
```

### `POST /api/records/bulk-delete`
Allows bulk deletion of records for an organization.
**Payload:**
```json
{
  "record_ids": [101, 102, 103]
}
```
**Response:**
```json
{
  "success": true,
  "message": "3 records deleted successfully."
}
```

### `POST /api/records/<rid>/update`
Updates an existing dynamic record, including processing calculated fields and file uploads.
**Payload:** `multipart/form-data` or `application/json`

## Communications & Webhooks

### `POST /webhooks/twilio/voice-status`
Receives asynchronous updates from Twilio regarding outbound voice calls.
**Parameters:** Standard Twilio StatusCallback payload (e.g., `CallSid`, `CallStatus`).

### `POST /webhooks/twilio/message-status`
Receives asynchronous status updates for WhatsApp and SMS messages (Queued, Sent, Delivered, Read, Failed).

## Global Configuration
All API limits are enforced by `Flask-Limiter` to prevent abuse. Global ratelimit is generally set to 100/minute per IP, with stricter limits on auth endpoints.
