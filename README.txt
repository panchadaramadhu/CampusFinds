CampusFind – Deployment notes

Environment variables for Render:
DATABASE_URL=your Supabase PostgreSQL connection URL
SECRET_KEY=a long random secret
CAMPUSFIND_ADMIN_USERNAME=Madhu
CAMPUSFIND_ADMIN_PASSWORD=m@dhu12345678
CAMPUSFIND_ADMIN_PASSWORD_HASH=optional Werkzeug password hash (preferred)
COOKIE_SECURE=1

Important: Never commit real passwords or DATABASE_URL values to GitHub.
The app uses CSRF protection, secure session cookies, login throttling, security headers,
input length validation, safer redirects, and restricted image uploads.

New feature: pickup_location is added automatically to existing databases when the app starts.


Updated claim workflow: submitting a claim sets Claim in Progress; admin approval sets Claimed; rejection returns the item to Open and restores Claim item.


NEW: Lost item cards now have an 'I Found This Item' action at the bottom. It opens a friendly pre-linked found-report form and connects the found report to the original lost report.
