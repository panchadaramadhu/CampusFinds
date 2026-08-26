import os
import io
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# Set SECRET_KEY in Render for persistent, secure sessions.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48)

database_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE, 'lostfound.db')}")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config.update(
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
)

db = SQLAlchemy(app)
ALLOWED = {"png", "jpg", "jpeg", "webp"}
ADMIN_USERNAME = os.environ.get("CAMPUSFIND_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("CAMPUSFIND_ADMIN_PASSWORD", "CampusFind@2026")
ADMIN_PASSWORD_HASH = os.environ.get("CAMPUSFIND_ADMIN_PASSWORD_HASH", "")

# Small in-memory login throttle. This blocks rapid guessing without adding a dependency.
_login_attempts = defaultdict(deque)


class Item(db.Model):
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    pickup_location = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=False)
    photo_data = db.Column(db.LargeBinary, nullable=True)
    photo_mime = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(30), default="Open", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Claim(db.Model):
    __tablename__ = "claims"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    roll_number = db.Column(db.String(100), nullable=False)
    proof = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    item = db.relationship("Item", backref=db.backref("claims", lazy=True))


class Feedback(db.Model):
    __tablename__ = "feedback"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), default="Anonymous")
    email = db.Column(db.String(200), default="")
    rating = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


with app.app_context():
    db.create_all()
    # Existing databases need the new pickup_location column too.
    try:
        db.session.execute(db.text("ALTER TABLE items ADD COLUMN pickup_location VARCHAR(200)"))
        db.session.commit()
    except Exception:
        db.session.rollback()


def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_forms():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not expected or not token or not secrets.compare_digest(token, expected):
            abort(400, "Invalid or expired form request. Please refresh the page and try again.")


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            flash("Please sign in as an administrator to access the admin portal.", "error")
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(value):
    if not value:
        return ""
    parsed = urlparse(value)
    return value if not parsed.netloc and value.startswith("/") else ""


def admin_password_ok(password):
    if ADMIN_PASSWORD_HASH:
        return check_password_hash(ADMIN_PASSWORD_HASH, password)
    return secrets.compare_digest(password, ADMIN_PASSWORD)


def login_allowed(ip):
    now = time.time()
    attempts = _login_attempts[ip]
    while attempts and now - attempts[0] > 300:
        attempts.popleft()
    return len(attempts) < 5


def clean(value, limit):
    return (value or "").strip()[:limit]


@app.route("/")
def home():
    q = clean(request.args.get("q"), 100)
    kind = clean(request.args.get("kind"), 20)
    query = Item.query
    if q:
        pattern = f"%{q}%"
        query = query.filter(db.or_(Item.title.ilike(pattern), Item.description.ilike(pattern), Item.location.ilike(pattern), Item.pickup_location.ilike(pattern)))
    if kind in ["Lost", "Found"]:
        query = query.filter_by(kind=kind)
    items = query.order_by(Item.id.desc()).all()
    lost = Item.query.filter_by(kind="Lost").count()
    found = Item.query.filter_by(kind="Found").count()
    feedback_count = Feedback.query.count()
    return render_template("home.html", items=items, q=q, kind=kind, lost=lost, found=found, feedback_count=feedback_count)


@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":
        kind = clean(request.form.get("kind"), 20)
        if kind not in {"Lost", "Found"}:
            abort(400)
        title = clean(request.form.get("title"), 200)
        category = clean(request.form.get("category"), 80) or "Other"
        location = clean(request.form.get("location"), 200)
        pickup_location = clean(request.form.get("pickup_location"), 200)
        description = clean(request.form.get("description"), 2000)
        if not title or not location or not description:
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("report"))

        f = request.files.get("photo")
        photo_data = photo_mime = None
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED:
                flash("Use PNG, JPG, JPEG or WEBP only.", "error")
                return redirect(url_for("report"))
            photo_data = f.read()
            if len(photo_data) > 5 * 1024 * 1024:
                flash("Photo must be 5 MB or smaller.", "error")
                return redirect(url_for("report"))
            if not (f.mimetype or "").startswith("image/"):
                flash("Please upload a valid image.", "error")
                return redirect(url_for("report"))
            photo_mime = f.mimetype

        db.session.add(Item(title=title, kind=kind, category=category, location=location,
                            pickup_location=pickup_location or None, description=description,
                            photo_data=photo_data, photo_mime=photo_mime))
        db.session.commit()
        flash("Item posted successfully!", "success")
        return redirect(url_for("home"))
    return render_template("report.html")


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        name = clean(request.form.get("name"), 150) or "Anonymous"
        email = clean(request.form.get("email"), 200)
        message = clean(request.form.get("message"), 1000)
        try:
            rating = int(request.form.get("rating", "5"))
        except ValueError:
            rating = 5
        rating = max(1, min(5, rating))
        if not message:
            flash("Please enter your feedback.", "error")
            return redirect(url_for("feedback"))
        db.session.add(Feedback(name=name, email=email, rating=rating, message=message))
        db.session.commit()
        flash("Thank you! Your feedback has been submitted.", "success")
        return redirect(url_for("feedback"))
    count = Feedback.query.count()
    avg = db.session.query(db.func.avg(Feedback.rating)).scalar() or 0
    return render_template("feedback.html", avg=round(float(avg), 1), count=count)


@app.route("/claim/<int:id>", methods=["GET", "POST"])
def claim(id):
    item = db.session.get(Item, id)
    if not item:
        return redirect(url_for("home"))
    if item.kind != "Found" or item.status != "Open":
        flash("This item is not available for a new claim.", "error")
        return redirect(url_for("home"))
    if request.method == "POST":
        student_name = clean(request.form.get("student_name"), 150)
        roll_number = clean(request.form.get("roll_number"), 100)
        proof = clean(request.form.get("proof"), 2000)
        if not student_name or not roll_number or not proof:
            flash("Please complete all claim details.", "error")
            return redirect(url_for("claim", id=id))
        db.session.add(Claim(item_id=id, student_name=student_name, roll_number=roll_number, proof=proof))
        db.session.commit()
        flash("Claim submitted for verification!", "success")
        return redirect(url_for("home"))
    return render_template("claim.html", item=item)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_url = safe_next(request.values.get("next", ""))
    if session.get("admin_authenticated"):
        return redirect(next_url or url_for("admin"))
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
        if not login_allowed(ip):
            flash("Too many login attempts. Please wait 5 minutes and try again.", "error")
            return render_template("admin_login.html", next=next_url), 429
        username = clean(request.form.get("username"), 150)
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USERNAME) and admin_password_ok(password):
            _login_attempts.pop(ip, None)
            session.clear()
            session["admin_authenticated"] = True
            session["admin_username"] = username
            session["_csrf_token"] = secrets.token_urlsafe(32)
            return redirect(next_url or url_for("admin"))
        _login_attempts[ip].append(time.time())
        flash("Invalid admin username or password.", "error")
    return render_template("admin_login.html", next=next_url)


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("You have been logged out of the admin portal.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin():
    claims = Claim.query.order_by(Claim.id.desc()).all()
    feedback = Feedback.query.order_by(Feedback.id.desc()).all()
    return render_template("admin.html", claims=claims, feedback=feedback)


@app.post("/admin/<int:id>/<action>")
@admin_required
def action(id, action):
    if action not in {"approve", "reject"}:
        abort(400)
    claim = db.session.get(Claim, id)
    if not claim:
        return redirect(url_for("admin"))
    if claim.status != "Pending":
        return redirect(url_for("admin"))
    claim.status = "Approved" if action == "approve" else "Rejected"
    if action == "approve":
        claim.item.status = "Claimed"
    db.session.commit()
    flash(f"Claim {claim.status.lower()}.", "success")
    return redirect(url_for("admin"))


@app.route("/uploads/<int:id>")
def uploads(id):
    item = db.session.get(Item, id)
    if not item or not item.photo_data:
        return ("", 404)
    return send_file(io.BytesIO(item.photo_data), mimetype=item.photo_mime or "application/octet-stream",
                     download_name=f"campusfind-{item.id}", conditional=True)


@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        return {"status": "error", "database": "unavailable"}, 503


@app.errorhandler(413)
def too_large(_):
    flash("Photo must be 5 MB or smaller.", "error")
    return redirect(url_for("report"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
