# ConnectFlow: Intelligent Workforce Communication Platform

![Platform Dashboard](static/dashboard_mockup.png)

**Version:** 2.0.0 (Updated Release)

ConnectFlow is a comprehensive enterprise SaaS (Software as a Service) platform designed to empower organizations to manage large-scale communication campaigns via automated WhatsApp messages and Voice calls.

Built with Python and Flask, the platform features a robust multi-tenant architecture with granular role-based access control (Platform Admin, Organization Admin, and Worker), billing & subscription management, and detailed delivery analytics.

A production-grade multi-tenant SaaS platform built for scale. It enables organizations to manage complex data structures through dynamic modules and engage customers via automated WhatsApp messaging and AI-driven voice calls.

## 🚀 Key Features

### 🏢 Multi-Tenant Architecture
- **Strict Isolation**: Secure data separation between organizations.
- **Role-Based Access Control (RBAC)**: Distinct permissions for Platform Admins, Organization Admins, and Workers.
- **Custom Branding**: Organizations can manage their own profiles, logos, and communication settings.

### 🛠️ Dynamic Module System
- **No-Code Data Modeling**: Create custom modules with flexible field types (String, Boolean, Calculated, etc.).
- **Logic Engine**: Automated field recalculations and conditional triggers.
- **Data Portability**: Comprehensive CSV/Excel import and export capabilities.

### 📢 Scalable Communication
- **WhatsApp Integration**: Dispatch text and voice messages using Twilio.
- **Voice Campaigns**: Automated calling features with multi-language support (via Twilio and Hooman Labs).
- **Campaign Analytics**: Detailed delivery logs and execution reports for every campaign.

### 💳 Subscription & Billing
- **Flexible Plans**: Manage multiple tiers of service with different feature sets.
- **Payment Lifecycle**: Support for various payment methods and subscription status tracking.

## 📁 Project Structure

```text
CUSTOMER CARE
+---communication           # Dispatchers for WhatsApp/Voice
+---models                  # SQLAlchemy Database Models
+---routes                  # Flask Blueprints (Admin, Org, Worker, API)
+---services                # Business Logic (Automation, Twilio, Hooman Labs)
+---static                  # CSS, JS, and Media Assets
+---templates               # HTML Templates (Jinja2)
|   +---admin               # Platform Admin Overlays
|   +---auth                # Authentication Flows
|   +---emails              # Notification Templates
|   +---errors              # HTTP Error Pages
|   +---legal               # Policies & TOS
|   +---main                # Public Landing & Registration
|   +---organization        # Tenant Admin Management
|   +---platform            # Super Admin Dashboard
|   \---worker              # Group & Module Execution
+---utils                   # Helper Decorators & Utilities
+---app.py                  # Application Entry Point
+---config.py               # Environment Configuration
+---translator.py           # Multi-language Translation Utility
\---voice_generator.py      # AI Text-to-Speech Engine
```

## 🛠️ Software & Technologies Used

### Core Frameworks
- **[Flask](https://flask.palletsprojects.com/)**: Primary web framework.
- **[SQLAlchemy](https://www.sqlalchemy.org/)**: Advanced ORM for complex data relationships.
- **[PostgreSQL](https://www.postgresql.org/)**: Production-ready relational database.

### Communication & AI
- **[Twilio](https://www.twilio.com/)**: WhatsApp API and Programmable Voice.
- **[gTTS (Google Text-to-Speech)](https://gtts.readthedocs.io/)**: Dynamic voice generation for campaigns.
- **[Googletrans](https://py-googletrans.readthedocs.io/)**: Real-time language translation.
- **[Edge-TTS](https://github.com/rany2/edge-tts)**: High-quality alternative voice engine.

### Data & Security
- **[Pandas](https://pandas.pydata.org/) & [Openpyxl](https://openpyxl.readthedocs.io/)**: Robust data import/export processing.
- **[Flask-Login](https://flask-login.readthedocs.io/)**: User session and role management.
- **[Flask-WTF](https://flask-wtf.readthedocs.io/)**: Secure form handling and CSRF protection.

## 🏁 Quick Start

### 1. Environment Setup
```bash
# Clone and enter the directory
python -m venv .venv
source .venv/Scripts/activate  # On Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file or set environment variables:
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/db_name
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
DEFAULT_TWILIO_NUMBER=whatsapp:+1415XXXXXXX
```

### 3. Execution
```bash
flask db upgrade  # If using migrations
python app.py
```

## 🔐 Administrative Access
The system automatically initializes a default platform admin:
- **Email**: `admin@gmail.com`
- **Password**: `123456`

> [!IMPORTANT]
> Change the default credentials immediately after first login in production environments.

## 👤 Developer Information

**Developer**: [Harshith KD](mailto:harshithkd032@gmail.com)  
**Profile**: Full Stack Developer & AI Enthusiast  
**Specialization**: SaaS Architecture, Automated Communication Systems, and Dynamic Data Modeling.

---

## 🚀 Key Features

### 1. Multi-Tiered Access & Roles
- **Platform Owner/Admin**: Global oversight. Can approve/suspend organizations, manage master subscription plans, configure platform-wide Twilio/communication settings, and view total system revenue.
- **Organization Admin**: Manages their specific tenant. Can purchase subscriptions, configure custom communication numbers (Twilio, Hooman Labs), add/remove workers, and view organization-wide campaign analytics.
- **Worker**: Executes the ground-level tasks. Can manage contact groups, build communication scripts (Text/Voice), and launch bulk campaigns.

### 2. Campaign Management & Automation
- **Multi-Channel**: Supports text campaigns (WhatsApp), voice campaigns, and hybrid WhatsApp voice notes using AI Text-to-Speech generation.
- **Dynamic Scripting**: Workers can create reusable scripts containing dynamic variables that automatically populate with contact details during delivery.
- **Bulk Execution**: Upload contacts via Excel/CSV, map them to groups, and trigger bulk asynchronous message/call dispatching using backend services.

### 3. SaaS & Billing Infrastructure
- **Subscription Engine**: Organizations must hold an active subscription to add workers and launch campaigns. Subscriptions handles Grace periods, Expiry lockdowns, and automated UI banners.
- **Usage Tracking**: Detailed logging of every processed message and call, recording success, failure, and Twilio/Service Provider SIDs for auditing.

### 4. Custom Communication Integrations
Organizations can rely on platform-default numbers OR configure their own integration credentials for:
- Twilio (Voice & WhatsApp)
- Hooman Labs (Indian Voice integration)

---

## 🏗 System Architecture & Tech Stack

**Backend**: 
- **Framework**: Flask (Python 3.x)
- **Database**: SQLAlchemy ORM (compatible with PostgreSQL in production, SQLite in dev). Migrations managed by Flask-Migrate.
- **Authentication**: Flask-Login and Werkzeug Security (Bcrypt hashing).
- **Audio Processing**: `gTTS` (Google Text-to-Speech) and `edge-tts` for generating voice clips from text scripts dynamically.

**Frontend**:
- **Templating**: Jinja2
- **Styling**: Bootstrap 5 with custom premium CSS tailored for modern SaaS aesthetics.
- **Interactivity**: Vanilla JavaScript and AJAX for dynamic form handling and validation.

**External API Integrations**:
- Twilio API (`twilio` python package)
- HTTP REST Requests (`http.client`) for Hooman Labs dispatch.

---

## 📂 Project Structure

```text
ConnectFlow/
├── app.py                   # Application factory, blueprint registration, app initialization
├── config.py                # Environment variables and configuration setup
├── requirements.txt         # Core dependencies
├── translator.py            # Utility for internal script translations
├── voice_generator.py       # Async AI Text-To-Speech generator
|
├── models/
│   └── models.py            # SQLAlchemy Database schemas (Orgs, Users, Campaigns, etc.)
│
├── routes/                  # Flask Blueprints
│   ├── admin.py             # Platform owner routes (/platform)
│   ├── org.py               # Organization admin routes (/org)
│   ├── worker.py            # Workforce operative routes (/worker)
│   ├── api.py               # Internal JSON endpoints
│   └── main.py              # Public landing page and authentication triggers
│
├── services/                # Business Logic & External API Controllers
│   ├── twilio_service.py    # Twilio dispatching logic
│   ├── hooman_labs_service.py# Hooman Labs dispatching logic
│   ├── notification_service.py # Internal platform alerts
│   ├── logic_engine.py      # Campaign execution logic
│   └── automation_engine.py # Background processing
│
├── static/                  # Public assets
│   ├── css/                 # Stylesheets (base.css, dashboard.css)
│   ├── js/                  # Frontend scripts
│   ├── audio/               # Generated TTS MP3 files
│   └── uploads/             # Org logos & Contact CSVs
│
└── templates/               # Jinja2 HTML Templates
    ├── auth/                # Login, Register, Forgot Password
    ├── platform/            # Platform Admin Views 
    ├── organization/        # Org Admin Views
    ├── worker/              # Worker execution views
    ├── legal/               # TOS & Privacy Policies
    └── base.html            # Master layout
```

---

## ⚙️ Local Development Setup

### 1. Prerequisites
Ensure you have the following installed:
- Python 3.9+
- pip (Python package manager)
- (Optional) PostgreSQL server if not using default SQLite.

### 2. Environment Variables
Create a `.env` file in the root directory based on the variables declared in `config.py`. Minimum required:
```env
SECRET_KEY=your_secure_random_key
DATABASE_URL=sqlite:///instance/dev.db
DEFAULT_ADMIN_EMAIL=admin@connectflow.com
DEFAULT_ADMIN_PASSWORD=SecurePassword123!
```
*(Optional: Add Twilio credentials to test default platform routing)*

### 3. Installation
Open your terminal and run:
```bash
# Clone the repository (if applicable)
# cd connectflow

# Install Dependencies
pip install -r requirements.txt

# Run the Application
python app.py
```
*The `app.py` script is designed to auto-create the database tables and the default Platform Admin user upon the first successful run.*

### 4. Accessing the Application
- **Platform Admin Dashboard**: `http://localhost:5000/platform/login`
- **Organization Registration**: `http://localhost:5000/register`
- **Organization Admin Login**: `http://localhost:5000/org/login`
- **Worker Login**: `http://localhost:5000/worker/login`
