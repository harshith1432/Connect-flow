# Customer Care: Multi-tenant SaaS Communication & Data Platform

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-green)
![Framework](https://img.shields.io/badge/framework-Flask-red)

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
- **Voice Campaigns**: Automated calling features with multi-language support.
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
+---services                # Business Logic (Automation, Twilio, Exotel)
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
- **Email**: `harshithkd032@gmail.com`
- **Password**: `123456`

> [!IMPORTANT]
> Change the default credentials immediately after first login in production environments.

## 👤 Developer Information

**Developer**: [Harshith KD](mailto:harshithkd032@gmail.com)  
**Profile**: Full Stack Developer & AI Enthusiast  
**Specialization**: SaaS Architecture, Automated Communication Systems, and Dynamic Data Modeling.

---

For a deeper dive into the software's architecture and design, please refer to the [Full Software Report](Report.md).
