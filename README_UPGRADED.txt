CampusFind - Upgraded Edition

Main upgrades:
- Username-based claims (roll number removed from the user-facing claim form).
- Duplicate active claim prevention.
- Users cannot claim their own found reports.
- "I found this" is protected from duplicate found reports.
- Persistent user notifications for found reports, claim submissions, approvals and rejections.
- User My Reports now includes notifications and clearer status tracking.
- Admin dashboard statistics for lost, found, pending claims, claimed items and users.
- Admin claim verification UI improved.
- Home page has category + status filters and search.
- Local development session cookies work over HTTP by default. For production set COOKIE_SECURE=1.
- Existing admin credentials remain configurable with CAMPUSFIND_ADMIN_USERNAME / CAMPUSFIND_ADMIN_PASSWORD.

Run on Windows:
1. Open this folder in VS Code.
2. Terminal -> New Terminal.
3. python -m pip install -r requirements.txt
4. python app.py
5. Open http://127.0.0.1:5000

Default admin login:
Username: Madhu
Password: m@dhu12345678

For deployment, set SECRET_KEY and preferably CAMPUSFIND_ADMIN_PASSWORD_HASH instead of using a plaintext admin password environment variable.
