CAMPUSFIND — ONLINE DATABASE VERSION

WHAT CHANGED
------------
- Replaced the local-only SQLite access layer with Flask-SQLAlchemy.
- The app automatically uses SQLite for local testing.
- When DATABASE_URL is set, it uses PostgreSQL, so records persist online.
- Reports, claims, feedback and uploaded photos are stored in the database.
- Added /health to test that the app can reach the database.
- Added Gunicorn and Render deployment files.
- Admin login remains protected.

LOCAL RUN
---------
1. Install Python 3.11+.
2. Open this folder in VS Code.
3. Run:
   python -m pip install -r requirements.txt
4. Run:
   python app.py
5. Open:
   http://127.0.0.1:5000

ONLINE DEPLOYMENT (RECOMMENDED: RENDER + SUPABASE POSTGRES)
-----------------------------------------------------------
1. Create a free Supabase project.
2. In Supabase, open Project Settings -> Database and copy a PostgreSQL connection string.
3. Put this project in a GitHub repository.
4. Create a Web Service on Render and connect the GitHub repository.
5. Build command:
   pip install -r requirements.txt
6. Start command:
   gunicorn app:app
7. Add these environment variables in Render:
   DATABASE_URL = your Supabase PostgreSQL connection string
   SECRET_KEY = a long random secret
   CAMPUSFIND_ADMIN_USERNAME = your admin username
   CAMPUSFIND_ADMIN_PASSWORD = your strong admin password
   COOKIE_SECURE = 1
8. Deploy.
9. Open your Render HTTPS URL. Visit /health. It should show:
   {"status":"ok","database":"connected"}

IMPORTANT
---------
The app creates the required database tables automatically on first start.
No SQLite database needs to be uploaded to the server.

DEFAULT ADMIN FOR LOCAL TESTING
-------------------------------
Username: admin
Password: CampusFind@2026

For an internet deployment, set your own admin username/password as environment variables. Do not publish them in GitHub.

PHOTO STORAGE
-------------
Photos are stored as binary data in PostgreSQL instead of the server's local filesystem.
This means photos remain available after a server restart/redeploy, as long as the database is retained.

SECURITY
--------
Use HTTPS in production, a strong SECRET_KEY, and a strong unique admin password.
Never commit real database passwords or admin passwords to GitHub.
