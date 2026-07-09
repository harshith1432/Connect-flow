# ConnectFlow

ConnectFlow is an Enterprise SaaS platform featuring a dynamic CRM dashboard built with a decoupled architecture. The platform consists of a **Next.js frontend** for lightning-fast user interactions and a **Flask backend** for robust API services, both fully integrated with **Supabase PostgreSQL**.

## 🏗 Architecture

- **Frontend (Next.js)**: Modern React framework using the App Router, Tailwind CSS for premium styling, and Lucide-React for iconography. Deployed on **Vercel**.
- **Backend (Flask)**: Python API monolith undergoing refactoring into an enterprise-grade Service/Repository pattern. Handles core business logic, third-party integrations (Twilio, Hooman Labs, Razorpay), and deployed on **Render**.
- **Database (Supabase)**: Remote PostgreSQL database handling authentication, storage, and dynamic records.

## 🚀 Getting Started

### 1. Local Development (Backend)
The backend is built with Python and Flask.

```bash
# Install dependencies
pip install -r requirements.txt

# Start the Flask development server
flask run
```

### 2. Local Development (Frontend)
The frontend is a Next.js application located in the `/frontend` directory.

```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` in your browser to view the CRM dashboard.

### 3. Data Migration
To migrate legacy SQLite data (`instance/dev.db`) into the new Supabase PostgreSQL production database, run the automated migration script:

```bash
python scripts/migrate_sqlite_to_supabase.py
```
*Ensure you have configured `DATABASE_URL` in your `.env` file to point to your Supabase instance.*

## 🔒 Environment Variables

### Frontend (`frontend/.env.local`)
- `NEXT_PUBLIC_SUPABASE_URL`: Your Supabase Project URL.
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`: Your Supabase Publishable Key.

### Backend (`.env`)
- `DATABASE_URL`: Connection string for Supabase PostgreSQL.
- `FLASK_ENV`: Set to `development` or `production`.
- *Refer to `.env.example` for the full list of third-party API keys (Twilio, Razorpay, Exotel).*

## 🚢 Deployment

- **Vercel**: The frontend is optimized for zero-config deployment on Vercel. Select `frontend` as your Root Directory during setup. The included `vercel.json` automatically proxies API requests to prevent CORS errors.
- **Render**: The backend is configured for deployment as a Web Service on Render via the included `render.yaml` configuration file.
