# ConnectFlow — Intelligent Workforce Communication Platform

**Version:** 4.0.0 (Enterprise SaaS — Full Public Release)

ConnectFlow is a high-trust, enterprise-grade SaaS platform designed to empower organizations to orchestrate large-scale communication campaigns via automated WhatsApp messages and Voice calls.

Featuring a modern feature-based modular architecture, the system enforces complete data isolation between tenants, integrates dynamic no-code data modeling, a full public-facing marketing website, and an intelligent lead management system built into the platform admin helpdesk.

![ConnectFlow Landing Page — Hero Section](app/features/public/static/landing_hero.png)

---

## 🚀 Key Features

### 🌐 Full Public Marketing Website (NEW)
- **Multi-Page Landing Site**: Professionally designed public-facing website built with custom CSS (no TailwindCSS dependency), covering:
  - `/` — Hero landing page with live animated stats and product preview
  - `/about` — Company story, team values, and mission
  - `/features` — Deep-dive feature showcase with icons and descriptions
  - `/solutions` — Use-case pages for Sales, Support, Marketing, and HR teams
  - `/pricing` — Tiered plans comparison with full FAQ section
  - `/contact` — Full inquiry/lead capture form (Name, Email, Phone, Company, Reason, Message)
  - `/help-center` — Categorized support articles and search
  - `/blog` — Blog listing page
  - `/careers` — Open positions and company culture
  - `/documentation` — Developer docs overview
  - `/api-reference` — Public REST API reference
  - `/changelog` — Version history and release notes
  - `/system-status` — Real-time platform status indicators
  - `/privacy-policy`, `/terms-of-service`, `/dpa` — Legal pages matching the platform theme

- **Talk to Sales / Talk to Us CTA**: Persistent call-to-action buttons across all public pages. Clicking opens a modal capturing: Name, Email, Phone, Company Name, and Reason — submitted directly as leads into the Platform Admin Helpdesk.

### 📬 Inquiry Lead Management System (NEW)
- **Unified Helpdesk with Tabs**: The Platform Admin Helpdesk now features two tabs in one page:
  - **Support Tickets** — Queries raised by Organization Admins and Workers, with Solve/Resolved actions
  - **New Inquiries** — Leads captured via Talk-to-Us and Contact forms from the public website
- **Lead Status Workflow**: Each inquiry moves through `New → Contacted → Qualified → Closed`
- **Admin Remark System**: Platform admins can add internal notes to any inquiry lead
- **Lead KPI Cards**: Real-time dashboard metrics showing total tickets, pending tickets, resolved tickets, and new inquiry count
- **Inquiry Filter**: Filter inquiries by status directly in the Helpdesk tab

### 🏢 Multi-Tenant Architecture & Data Isolation
- **Strict Tenant Separation**: Dynamic partitioning guarantees organizations never see or access cross-tenant records.
- **Granular RBAC**: Distinct permissions and custom views for **Platform Owners (Super Admins)**, **Organization Admins (Tenants)**, and **Workers (Operatives)**.
- **Custom Integration Keys**: Tenants can use default platform communication credits or input their custom credentials for Twilio/Hooman Labs.

### 🛠️ Dynamic Module System (No-Code CRM)
- **Flexible Fields Mapping**: Create custom communication modules dynamically with field types including text fields, boolean parameters, and calculated fields.
- **Logic & Calculation Engine**: Automatically recalculates values based on conditional triggers upon record modification.
- **Bulk Data Portability**: Executive-grade Excel and CSV bulk import, schema mapping, validation, and export capabilities.

### 📢 Scalable Communication & AI Text-to-Speech
- **Twilio SMS & WhatsApp**: Dispatch dynamic text scripts directly via WhatsApp.
- **Automated Voice Campaigns**: Outbound cold-call automation with multi-language translation and custom text speech synthesis.
- **Dual TTS Engine**: Dynamic high-fidelity speech synthesis utilizing gTTS (Google Text-to-Speech) and Microsoft Edge-TTS interfaces.
- **Real-Time Delivery Auditing**: Interactive call log tracking with webhook-driven status synchronization.

### 💳 Real-Time Billing & High-Fidelity Invoicing
- **Live Payments Ledger**: Automated, dynamically populated payment history tailored per organization tier.
- **Commercial Tax Invoicing**: Generates live, printable, high-fidelity digital tax invoices (featuring CGST/SGST breakdowns and secure gateway declarations).
- **Checkout Infrastructure**: Interactive enterprise checkout interface supporting multi-provider integration (e.g., Razorpay Standard).

### 🎨 Modernized User Experience & Core UI
- **Dynamic Theme System**: Fully integrated Dark Mode and Light Mode switching applied seamlessly across all dashboard views.
- **Premium User Profiles**: State-of-the-art dual-pane split UI standardizations deployed across both Organization Admin and Worker dashboards.
- **Real-Time Resource KPIs**: Live tracking of plan limits (worker seats, message volumes, active campaigns) with visual utilization progress bars.
- **Responsive Navigation**: Modular sidebars and layouts adapted specifically for Premium Billing, Subscription management, and operative dashboards.

---

## 🔐 Enterprise SaaS Security Architecture

ConnectFlow is architected with advanced, startup-grade security layers to protect tenant data, prevent session hijacking, and safeguard interactive interfaces.

### 1. Multi-Factor Authentication (MFA) & Secure Authentication
- **Service Orchestration (`app/security/mfa.py`)**: Centralized MFA (`MFAService`) supports Time-Based One-Time Passwords (TOTP via Google Authenticator) and secure fallback OTPs.
- **Resend Token Limiting**: Enforces strict throttling on request frequencies (max 1 OTP per 60 seconds).
- **Cryptographic Token Lifecycle**: Single-use tokens are automatically deleted upon consumption, eliminating replay vectors.

### 2. Deep Session Lifecycle Management
- **Fixation Defense (`app/security/session_manager.py`)**: Regenerates Flask session IDs immediately upon login/logout.
- **Inactivity Timeout**: Automatically invalidates sessions after 20 minutes of inactivity.
- **Absolute Session Timeout**: Enforces a strict 2-hour absolute limit on active login sessions.
- **Active Device Tracking**: Registers session variables with device-specific headers (IP, User-Agent) to block session-jacking.

### 3. Transport, Rate Limiting & HTTP Protection
- **Request Throttling (`app/security/rate_limit.py`)**: Integrated rate limiting using `Flask-Limiter` with custom tenant thresholds.
- **Security Headers (`app/security/security_headers.py`)**: Hardened HTTP headers on every request:
  - **CSP**: Strict rules restricting script, style, and media injection vectors.
  - **HSTS**: 1-year default HTTPS enforcement cache.
  - **X-Content-Type-Options**: Blocks MIME-type sniffing.
  - **X-Frame-Options**: Enforces `DENY` / `SAMEORIGIN` to eliminate Clickjacking.
  - **Referrer-Policy**: Restricts referrer exposure to `strict-origin-when-cross-origin`.
- **CSRF Safety**: Comprehensive Cross-Site Request Forgery security via `Flask-WTF`. Webhooks and public API ingress controllers cleanly exempted.

### 4. Continuous Threat Monitoring
- **Suspicious Request Tracking (`app/security/suspicious_activity.py`)**: Continuously monitors logs for anomalous behavior patterns.
- **Automated Account Lockdown**: Instantly freezes high-risk user records and logs trace alerts in platform dashboards.

---

## 🏗 Modular Project Architecture

The codebase follows a **Feature-Based Modular Architecture**. All core elements, templates, and routes are organized by their business domain/feature module.

```text
connectflow/
├── run.py                              # Unified WSGI entry point
├── requirements.txt                    # Production library dependencies
│
└── app/                                # Application Root Package
    ├── __init__.py                     # Flask App Factory, WSGI Lifecycle Hooks
    ├── extensions.py                   # Centralized shared objects (DB, Migrate, Limiter, CSRF)
    ├── config.py                       # Platform configuration adapter
    │
    ├── core/                           # Core Platform Utility Adapters
    │   ├── constants.py                # Global Enumerations and platform constant limits
    │   ├── decorators.py               # Authorization, role checking decorators
    │   ├── helpers.py                  # Generic utility formatting functions
    │   └── permissions.py              # Organization resource ownership validators
    │
    ├── models/                         # Shared Relational Database Schemas (SQLAlchemy)
    │   ├── __init__.py                 # Schema registry — imports all models
    │   ├── campaigns.py                # Outbound campaigns, call logs, webhook meta
    │   ├── change_requests.py          # Module modification database logs
    │   ├── chat.py                     # Chat message schema
    │   ├── helpdesk.py                 # Support ticket schema (HelpdeskQuery)
    │   ├── inquiry.py                  # Public inquiry / Talk-to-Us lead schema (NEW)
    │   ├── modules.py                  # Custom dynamic CRM modules and fields schema
    │   ├── organization.py             # Tenant profiles, billing plans, subscriptions
    │   ├── platform.py                 # Platform Super Admin credentials schema
    │   ├── scripts.py                  # Dynamic outreach text and call script templates
    │   ├── security.py                 # Sessions, OTP registry, device signatures
    │   └── worker.py                   # Workforce user profile schema
    │
    ├── security/                       # Enterprise SaaS Security Stack
    │   ├── auth_protection.py          # Brute-force and login guard layers
    │   ├── mfa.py                      # MFA Service (TOTP, OTPs, backup codes)
    │   ├── rate_limit.py               # API route throttle rate controllers
    │   ├── routes.py                   # Security route blueprint (OTP entry, challenges)
    │   ├── security_headers.py         # HTTP Response Security Headers Middleware
    │   ├── session_manager.py          # Session ID regeneration, timeout managers
    │   └── suspicious_activity.py      # Threat vectors logging and request monitor
    │
    ├── common/                         # Global Functional Utilities & Service Dispatchers
    │   ├── audio/
    │   │   └── generator.py            # TTS generator service (gTTS / Edge-TTS)
    │   ├── translation/
    │   │   └── translator.py           # Speech script translation controller
    │   └── notifications/
    │       ├── service.py              # Low-level notification orchestrator
    │       ├── twilio.py               # Twilio dispatch handler (Voice / WhatsApp)
    │       └── hooman_labs.py          # Hooman Labs API voice dialer
    │
    ├── features/                       # Feature-Based Route Blueprints
    │   │
    │   ├── public/                     # Public Marketing Website
    │   │   ├── static/
    │   │   │   ├── landing.css         # Custom landing page stylesheet (no Tailwind)
    │   │   │   ├── landing_hero.png    # Hero section image
    │   │   │   ├── landing_features.png# Features section image
    │   │   │   └── analytics_preview.png# Dashboard preview image
    │   │   ├── templates/
    │   │   │   ├── index.html          # Main landing page (hero, stats, preview, CTA)
    │   │   │   ├── main/               # All public content pages
    │   │   │   │   ├── about.html      # Company story and mission
    │   │   │   │   ├── features.html   # Full product features showcase
    │   │   │   │   ├── solutions.html  # Industry/use-case pages
    │   │   │   │   ├── pricing.html    # Tiered plans + FAQ
    │   │   │   │   ├── contact.html    # Contact / Inquiry form → leads
    │   │   │   │   ├── help_center.html# Support knowledge base
    │   │   │   │   ├── blog.html       # Blog listing
    │   │   │   │   ├── careers.html    # Open positions
    │   │   │   │   ├── documentation.html # Developer docs overview
    │   │   │   │   ├── api_reference.html # REST API reference
    │   │   │   │   ├── changelog.html  # Version history
    │   │   │   │   ├── system_status.html # Platform status indicators
    │   │   │   │   └── subscription_expired.html # Plan expiry notice
    │   │   │   └── legal/
    │   │   │       ├── privacy_policy.html  # Privacy Policy (themed)
    │   │   │       ├── terms_of_service.html# Terms of Service (themed)
    │   │   │       └── dpa.html             # Data Processing Agreement (themed)
    │   │   └── routes.py               # Landing, auth, registration, inquiry submission
    │   │
    │   ├── super_admin/                # Platform Owner (Super Admin) Interface
    │   │   ├── templates/
    │   │   │   └── platform/
    │   │   │       ├── dashboard.html      # Platform-wide KPI overview
    │   │   │       ├── helpdesk.html       # Unified Helpdesk: Support Tickets + New Inquiries tabs
    │   │   │       ├── notifications.html  # Platform notification center
    │   │   │       ├── org_detail.html     # Organization detail view
    │   │   │       ├── pending_changes.html# Pending change request reviews
    │   │   │       ├── settings_admins.html# Admin user management
    │   │   │       ├── settings_payments.html # Payment gateway settings
    │   │   │       └── settings_plans.html # Subscription plan configuration
    │   │   └── routes.py               # Platform controls, org verification, helpdesk, inquiries
    │   │
    │   ├── tenant_admin/               # Organization Administrator Interface
    │   │   ├── templates/              # Org admin workspace, billing, invoices, checkout
    │   │   └── routes.py               # Org admin workspace, workers, premium plans, billing
    │   │
    │   ├── workforce/                  # Worker Operative Interface
    │   │   ├── templates/              # Worker profiles, modules, scripts
    │   │   └── routes.py               # Worker campaigns, dynamic spreadsheet modifications
    │   │
    │   ├── api/
    │   │   └── routes.py               # REST endpoints for charts, translations, calculations
    │   │
    │   └── webhooks/
    │       └── routes.py               # Webhook ingestion for Twilio status callbacks
    │
    ├── static/                         # Global Shared Static Assets
    │   ├── css/                        # Shared stylesheets (dashboard, base layouts)
    │   ├── js/                         # Shared JavaScript logic
    │   └── uploads/                    # User uploaded assets
    │
    └── templates/                      # Global Shared Layout Templates
        ├── auth/                       # Shared Access Denied templates
        ├── base.html                   # Main dashboard layout framework
        ├── base_auth_premium.html      # Premium login stylesheet framing
        ├── base_billing_premium.html   # Billing workflow layout wrapper
        ├── base_org_premium.html       # Dedicated tenant admin layout wrapper
        ├── base_platform_premium.html  # Dedicated platform admin layout wrapper (sidebar nav)
        └── base_worker_premium.html    # Dedicated worker operative layout wrapper
```

---

## 🛠️ Software & Technologies Used

### Core Frameworks
- **Flask (v2.x/v3.x)**: Principal microservices web application layer.
- **SQLAlchemy (ORM)**: Enterprise schema creation and relational mapping.
- **PostgreSQL**: Production engine. Works natively with SQLite in local environments.
- **Flask-Migrate (Alembic)**: Database schema versioning and migration management.

### Voice & Communication Services
- **Twilio SDK**: High-availability SMS/WhatsApp delivery and voice dialers.
- **gTTS (Google TTS) & Edge-TTS**: Flexible Text-To-Speech engines for customized prompt audios.
- **Googletrans**: Automatic language translator adapter.

### Production Security Libraries
- **Flask-Login**: Active secure authenticated session loaders.
- **Flask-WTF**: Cryptographic form tokens defending against CSRF exploits.
- **Flask-Limiter**: Redis/Memory backed rate-limiting layer.
- **Cryptography & Bcrypt**: Password hashing and token security.

### Frontend & UI
- **Vanilla CSS** (`landing.css`): Custom-built landing page styles — no Tailwind or external CSS frameworks.
- **Bootstrap 5**: Dashboard layout grid and utility classes.
- **Bootstrap Icons**: Icon library across all interfaces.

---

## 🏁 Quick Start & Run Instructions

### 1. Environment Initialization
```bash
git clone https://github.com/harshith1432/Connect-flow.git
cd Connect-flow
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configuration Setup
Create a `.env` file in the root directory:
```env
SECRET_KEY=generate_a_cryptographically_secure_random_key_here
DATABASE_URL=sqlite:///instance/dev.db

# Default Platform Admin Credentials
DEFAULT_ADMIN_EMAIL=admin@connectflow.com
DEFAULT_ADMIN_PASSWORD=SecurePassword123!

# Twilio Integration (Optional)
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
DEFAULT_TWILIO_NUMBER=whatsapp:+14155552671
```

### 3. Database Initialization & Boot
```bash
python run.py
```
> The platform dynamically checks database tables and seeds the default Platform Administrator on first boot. Look for `APP READY` in the console output.

### 4. Interface Endpoints

| Interface | URL |
|---|---|
| Public Marketing Site | `http://localhost:5000/` |
| Platform Owner (Super Admin) | `http://localhost:5000/platform/` |
| Organization Admin Workspace | `http://localhost:5000/org/` |
| Worker Operative Workspace | `http://localhost:5000/worker/` |

---

## 📋 Platform Admin — Route Reference

| Route | Description |
|---|---|
| `/platform/dashboard` | Platform-wide KPI overview |
| `/platform/plans` | Subscription plan management |
| `/platform/payments` | Payment gateway settings |
| `/platform/admins` | Platform admin user management |
| `/platform/pending-reviews` | Organization change request reviews |
| `/platform/helpdesk` | Support Tickets tab |
| `/platform/helpdesk#inquiries` | New Inquiries (Talk-to-Us leads) tab |
| `/platform/notifications` | Platform notification center |

---

## 📋 Public Site — Route Reference

| Route | Description |
|---|---|
| `/` | Main landing page |
| `/about` | Company story and mission |
| `/features` | Product features showcase |
| `/solutions` | Use-case and industry pages |
| `/pricing` | Plans and pricing + FAQ |
| `/contact` | Contact form (captured as leads) |
| `/help-center` | Knowledge base and support |
| `/blog` | Blog listing |
| `/careers` | Open positions |
| `/documentation` | Developer documentation |
| `/api-reference` | REST API reference |
| `/changelog` | Version history |
| `/system-status` | Real-time platform status |
| `/privacy-policy` | Privacy Policy |
| `/terms-of-service` | Terms of Service |
| `/dpa` | Data Processing Agreement |

---

## 👤 Developer Profile

**Developer**: [Harshith KD](mailto:harshithkd032@gmail.com)
**Role**: Full Stack SaaS Developer & AI Systems Engineer
**GitHub**: [github.com/harshith1432](https://github.com/harshith1432)
**Aesthetic Focus**: Executive-grade monochrome design patterns, fast asynchronous execution pipelines, and rock-solid SaaS architecture.

---

*ConnectFlow v4.0.0 — Built with precision. Designed for scale.*
