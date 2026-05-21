# ConnectFlow: Intelligent Workforce Communication Platform

**Version:** 3.0.0 (Enterprise SaaS Production Release)

ConnectFlow is a high-trust, enterprise-grade SaaS (Software as a Service) platform designed to empower organizations to orchestrate large-scale communication campaigns via automated WhatsApp messages and Voice calls. 

Featuring a modern, feature-based modular architecture, the system enforces complete data isolation between tenants, integrates dynamic no-code data modeling, and implements robust, startup-grade security standards.

![ConnectFlow Landing Page — Hero Section](static/landing_hero.png)

![ConnectFlow Landing Page — Features Overview](static/landing_features.png)

---

## 🚀 Key Features

### 🏢 Multi-Tenant Architecture & Data Isolation
- **Strict Tenant Separation**: Dynamic partitioning guarantees organizations never see or access cross-tenant records.
- **Granular RBAC**: Distinct permissions and custom views for **Platform Owners (Super Admins)**, **Organization Admins (Tenants)**, and **Workers (Operatives)**.
- **Custom Integration Keys**: Tenants can use default platform communication credits or input their custom credentials for Twilio/Hooman Labs.

### 🛠️ Dynamic Module System (No-Code CRM)
- **Flexible Fields Mapping**: Create custom communication modules dynamically with field types including text fields, boolean parameters, and calculated fields.
- **Logic & Calculation Engine**: Automatically recalculates values based on conditional triggers and calculations upon record modification.
- **Bulk Data Portability**: Executive-grade Excel and CSV bulk import, schema mapping, validation, and export capabilities.

### 📢 Scalable Communication & AI Text-to-Speech
- **Twilio SMS & WhatsApp**: Dispatch dynamic text scripts directly via WhatsApp.
- **Automated Voice Campaigns**: Outbound cold-call automation with multi-language translation and custom text speech synthesis.
- **Dual TTS Engine**: Dynamic high-fidelity speech synthesis utilizing gTTS (Google Text-to-Speech) and Microsoft Edge-TTS interfaces.
- **Real-Time Delivery Auditing**: Interactive call log tracking with webhook-driven status synchronization.

### 💳 Real-Time Billing & High-Fidelity Invoicing (NEW)
- **Live Payments Ledger**: Automated, dynamically populated payment history tailored per organization tier.
- **Commercial Tax Invoicing**: Generates live, printable, high-fidelity digital tax invoices (featuring CGST/SGST breakdowns and secure gateway declarations).
- **Checkout Infrastructure**: Interactive enterprise checkout interface supporting multi-provider integration (e.g., Razorpay Standard).

### 🎨 Modernized User Experience & Core UI (NEW)
- **Dynamic Theme System**: Fully integrated Dark Mode and Light Mode switching applied seamlessly across all dashboard views.
- **Premium User Profiles**: State-of-the-art dual-pane split UI standardizations deployed across both Organization Admin and Worker dashboards for maximum clarity.
- **Real-Time Resource KPIs**: Live tracking of plan limits (worker seats, message volumes, active campaigns) with visual utilization progress bars and dynamic usage scoring.
- **Responsive Navigation Structure**: Modular sidebars and layouts adapted specifically for Premium Billing, Subscription management, and operative dashboards.

---

## 🔐 Enterprise SaaS Security Architecture

ConnectFlow is architected with advanced, startup-grade security layers to protect tenant data, prevent session hijacking, and safeguard interactive interfaces.

### 1. Multi-Factor Authentication (MFA) & Secure Authentication
- **Service Orchestration (`app/security/mfa.py`)**: Centralized Multi-Factor Authentication (`MFAService`) supports Time-Based One-Time Passwords (TOTP via Google Authenticator) and secure fallback OTPs.
- **Resend Token Limiting**: Enforces strict throttling on request frequencies (e.g., maximum of 1 OTP request per 60 seconds) to prevent SMS/email gateway resource drain.
- **Fallback Verification**: Generates single-use secure cryptographically signed numeric tokens and cryptographic multi-use backup codes.
- **Cryptographic Token Lifecycle**: Single-use tokens are automatically deleted and invalidated upon single consumption, regardless of success, eliminating replay vectors.

### 2. Deep Session Lifecycle Management
- **fixation Defense (`app/security/session_manager.py`)**: Regenerates Flask session IDs immediately upon user login/logout, protecting against session fixation hijacking.
- **Inactivity Timeout**: Automatically invalidates and signs out active sessions after 20 minutes of user inactivity.
- **Absolute Session Timeout**: Enforces a strict absolute limit (e.g., 2 hours) on active login sessions, prompting a secure login challenge.
- **Active Device Tracking**: Registers and tracks session variables with device-specific headers (IP Address, User-Agent) to block session-jacking or cross-environment token hijacking.
- **Centralized Session Invalidation**: Instantly revokes sessions and destroys database token links across all nodes during updates or security breaches.

### 3. Transport, Rate Limiting & HTTP Protection
- **Request Throttling (`app/security/rate_limit.py`)**: Integrated rate limiting using `Flask-Limiter` with custom tenant thresholds. Protects auth endpoints, static scripts, and webhooks against brute-force and DDoS patterns.
- **Security Headers (`app/security/security_headers.py`)**: Inject secure, hardened HTTP headers on every request lifecycle:
  - **Content Security Policy (CSP)**: Strict rules restricting script, style, and media injection vectors.
  - **HTTP Strict Transport Security (HSTS)**: 1-year default HTTPS enforcement cache.
  - **X-Content-Type-Options**: Blocks MIME-type sniffing (`nosniff`).
  - **X-Frame-Options**: Enforces `DENY` or `SAMEORIGIN` to eliminate Clickjacking.
  - **Referrer-Policy**: Restricts referrer exposure to `strict-origin-when-cross-origin`.
  - **Permissions-Policy**: Restricts microphone, geolocation, and camera inputs.
- **CSRF Safety & Exemption Routing**: Comprehensive Cross-Site Request Forgery security via `Flask-WTF`. Webhooks and public API ingress controllers are cleanly exempted via strict token-authenticated endpoints.

### 4. Continuous Threat Monitoring
- **Suspicious Request Tracking (`app/security/suspicious_activity.py`)**: Continuously monitors incoming logs for anomalous behavior (e.g., access pattern modifications, extreme request frequency spikes, rapid geolocation shifts).
- **Automated Account Lockdown**: Instantly freezes high-risk user records and logs trace alerts in platform dashboards.

---

## 🏗 Modular Project Architecture

The codebase has been transformed from a standard monolithic layout into a **Feature-Based Modular Architecture**. All core elements, templates, and routes are organized by their business domain/feature module, maximizing maintainability and enterprise scalability.

```text
CUSTOMER CARE (connectflow)
├── run.py                          # Unified WSGI entry point 
├── requirements.txt                # Production library dependencies
├── config.py                       # Global platform variables and database configurations
│
└── app/                            # Application Root Package
    ├── __init__.py                 # Flask App Factory, WSGI Request Log, Lifecycle Hooks
    ├── extensions.py               # Centralized shared global objects (DB, Migrate, Limiter, CSRF)
    ├── config.py                   # Platform configuration adapter
    │
    ├── core/                       # Core Platform Utility Adapters
    │   ├── constants.py            # Global Enumerations and platform constant limits
    │   ├── decorators.py           # Authorization, role checking (Super Admin, Tenant Admin, Worker)
    │   ├── helpers.py              # Generic utility formatting functions
    │   └── permissions.py          # Organization resource ownership validators
    │
    ├── models/                     # Shared Relational Database Schemas (SQLAlchemy)
    │   ├── __init__.py             # Relational schema registry
    │   ├── campaigns.py            # Outbound campaigns, calls logs and webhook meta schema
    │   ├── change_requests.py      # Module modification database logs
    │   ├── modules.py              # Custom Dynamic CRM modules layouts and fields schema
    │   ├── organization.py         # Tenant profiles, billing plans, and subscriptions schema
    │   ├── platform.py             # Platform Super Admin credentials schema
    │   ├── scripts.py              # Dynamic outreach text and call script templates schema
    │   ├── security.py             # Session tracks, OTP registry, device signature metadata schema
    │   └── worker.py               # Workforce user profile schema
    │
    ├── security/                   # Enterprise SaaS Security Stack
    │   ├── auth_protection.py      # Brute-force and login guard layers
    │   ├── mfa.py                  # Multi-Factor Service (TOTP, single-use secure OTPs, backup codes)
    │   ├── rate_limit.py           # API route throttle rate controllers
    │   ├── routes.py               # Security route blueprint (OTP entry, verify challenges)
    │   ├── security_headers.py     # HTTP Response Security Headers Middleware (CSP, HSTS, etc.)
    │   ├── session_manager.py      # Session ID regeneration, absolute/inactivity timeout managers
    │   └── suspicious_activity.py  # Threat vectors logging and request monitor
    │
    ├── common/                     # Global Functional Utilities & Service Dispatchers
    │   ├── audio/
    │   │   └── generator.py        # Text-To-Speech generator service (gTTS / Edge-TTS options)
    │   ├── translation/
    │   │   └── translator.py       # Speech script translation controller
    │   └── notifications/
    │       ├── service.py          # Low-level notification orchestrator
    │       ├── twilio.py           # Twilio dispatch handler (Voice calls / WhatsApp dispatching)
    │       └── hooman_labs.py      # Hooman Labs API programmatic voice dialer
    │
    ├── features/                   # Feature-based Route Blueprints
    │   ├── api/
    │   │   └── routes.py           # REST endpoints for charts, script translations, calculations
    │   ├── public/
    │   │   ├── static/             # Public specific assets (landing images, css)
    │   │   ├── templates/          # Public specific templates (legal, auth, index)
    │   │   └── routes.py           # Marketing landing, org registration, authentication routes
    │   ├── super_admin/
    │   │   ├── templates/          # Platform Admin specific templates (platform/, auth/)
    │   │   └── routes.py           # Platform Owner controls, plans configuration, organization verification
    │   ├── tenant_admin/
    │   │   ├── templates/          # Tenant Admin specific templates (organization/, auth/, billing, invoices, checkout)
    │   │   └── routes.py           # Org admin workspace, workers management, premium plans, dynamic billing
    │   ├── webhooks/
    │   │   └── routes.py           # Webhook response ingestion APIs for Twilio status callbacks
    │   └── workforce/
    │       ├── templates/          # Worker specific templates (worker profiles, modules, scripts)
    │       └── routes.py           # Worker operative campaigns setup, dynamic spreadsheet modifications
    │
    ├── static/                     # Global Shared Static Assets
    │   ├── css/                    # Shared stylesheets (dashboard, base layouts)
    │   ├── js/                     # Shared JS logic
    │   └── uploads/                # User uploaded assets
    │
    └── templates/                  # Global Shared Layout Templates
        ├── auth/                   # Shared Access Denied templates
        ├── base.html               # Main dashboard layout framework
        ├── base_auth_premium.html  # Premium login stylesheet framings
        ├── base_org_premium.html   # Dedicated tenant admin layout wrapper
        ├── base_platform_premium.html# Dedicated platform admin layout wrapper
        └── base_worker_premium.html# Dedicated operator layout wrapper
```

---

## 🛠️ Software & Technologies Used

### Core Frameworks
- **Flask (v2.x/v3.x)**: Principal microservices web application layer.
- **SQLAlchemy (ORM)**: Enterprise schema creation and relational mapping.
- **PostgreSQL**: Production engine. Works natively with SQLite in local environments.

### Voice & Communication Services
- **Twilio SDK**: High-availability SMS/WhatsApp delivery and voice dialers.
- **gTTS (Google TTS) & Edge-TTS**: Flexible Text-To-Speech engines rendering customized prompt audios on the fly.
- **Googletrans**: Automatic language translator adapter.

### Production Security Libraries
- **Flask-Login**: Active secure authenticated session loaders.
- **Flask-WTF**: Cryptographic form tokens defending against CSRF exploits.
- **Flask-Limiter**: Redis/Memory backed rate-limiting layer.
- **Cryptography & Bcrypt**: Password hashing and token security.

---

## 🏁 Quick Start & Run Instructions

### 1. Environment Initialization
```bash
# Clone the repository and navigate to the directory
python -m venv .venv
source .venv/Scripts/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration Setup
Create a `.env` file in the root directory:
```env
SECRET_KEY=generate_a_cryptographically_secure_random_key_here
DATABASE_URL=sqlite:///instance/dev.db # Or postgresql://user:pass@localhost:5432/db_name

# Default Platform Admin Credentials
DEFAULT_ADMIN_EMAIL=admin@connectflow.com
DEFAULT_ADMIN_PASSWORD=SecurePassword123!

# External API Integration Settings (Optional for verification)
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
DEFAULT_TWILIO_NUMBER=whatsapp:+14155552671
```

### 3. Database Initialization & Boot
```bash
# Apply migrations or initialize models schema
python run.py
```
*Note: The platform is engineered to dynamically check database tables and seed the default Platform Administrator upon start. The WSGI logging system will output `APP READY: ANTIGRAVITY HOOMAN WEBHOOKS ENABLED` indicating a clean startup status.*

### 4. Unified Interface Endpoints
- **Marketing Page & Logins**: `http://localhost:5000/`
- **Platform Owner Interface**: Prefixed route `/platform`
- **Organization Administrator Workspace**: Prefixed route `/org`
- **Worker Workspace**: Managed routes via workforce blueprints

---

## 👤 Developer Profile

**Developer**: [Harshith KD](mailto:harshithkd032@gmail.com)  
**Role**: Full Stack SaaS Developer & AI Systems Engineer  
**Aesthetic Focus**: Executive-grade monochrome design patterns, fast asynchronous execution pipelines, and rock-solid SaaS architecture.
