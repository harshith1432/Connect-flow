# ConnectFlow Architecture

## System Overview
ConnectFlow is an enterprise-grade SaaS application designed for orchestrating large-scale communication campaigns via automated WhatsApp messages and Voice calls.

It uses a modular, feature-based architecture to guarantee high maintainability and security. The core stack includes:
- **Backend:** Python, Flask, SQLAlchemy (ORM)
- **Database:** PostgreSQL (production), SQLite (development)
- **Frontend:** HTML5, CSS3 (Vanilla), JavaScript, Bootstrap 5

## Module Architecture

The application is structured around isolated domain modules:

- **Public Marketing Website (`app/features/public`)**: Handles all unauthenticated traffic, marketing landing pages, legal pages, and lead capture.
- **Platform Owner (`app/features/super_admin`)**: The core control plane for super administrators to manage tenants (organizations), global settings, pricing plans, and the unified Helpdesk for both support tickets and public inquiries.
- **Organization Admin (`app/features/tenant_admin`)**: The administrative portal for each tenant to manage their workforce, campaigns, billing, and modules.
- **Workforce Operative (`app/features/workforce`)**: The portal for workers to manage dynamic modules, make updates to records, and track communication logic.

## Security Layers

1. **Authentication:** Uses Time-Based One-Time Passwords (TOTP) and fallback OTPs via a central `MFAService`.
2. **Session Management:** Hardened session management with fixation defense, inactivity timeouts, and device tracking to prevent session hijacking.
3. **Data Protection:** Strict tenant separation via organizational RBAC ensures data isolation between different clients.

## Communication Subsystems

- **Twilio Integration:** Dispatches dynamic text scripts directly via WhatsApp and standard SMS.
- **Voice Campaigns:** Automated outbound cold-call sequences leveraging gTTS and Microsoft Edge-TTS for dynamic speech synthesis, coupled with real-time webhook tracking.

## Dynamic Modules (No-Code CRM)

ConnectFlow includes a highly flexible field-mapping CRM engine. Users can:
- Map dynamic attributes (text, boolean, calculated, date, select)
- Trigger mathematical or logical formulas dynamically based on field states
- Bulk import and export data securely within the tenant's isolated storage
