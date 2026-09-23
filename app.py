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
from werkzeug.security import check_password_hash, generate_password_hash

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
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)

db = SQLAlchemy(app)
ALLOWED = {"png", "jpg", "jpeg", "webp"}
ADMIN_USERNAME = os.environ.get("CAMPUSFIND_ADMIN_USERNAME", "Madhu")
ADMIN_PASSWORD = os.environ.get("CAMPUSFIND_ADMIN_PASSWORD", "m@dhu12345678")
ADMIN_PASSWORD_HASH = os.environ.get("CAMPUSFIND_ADMIN_PASSWORD_HASH", "")

# Small in-memory login throttle. This blocks rapid guessing without adding a dependency.
_login_attempts = defaultdict(deque)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    profile_photo = db.Column(db.LargeBinary, nullable=True)
    profile_photo_mime = db.Column(db.String(50), nullable=True)


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
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # If this is a Found report created from a Lost report, keep the connection.
    linked_lost_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    reporter = db.relationship("User", foreign_keys=[reporter_id])


class Claim(db.Model):
    __tablename__ = "claims"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])
    user_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    roll_number = db.Column(db.String(100), nullable=False)
    proof = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    item = db.relationship("Item", backref=db.backref("claims", lazy=True))


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(300), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user = db.relationship("User", foreign_keys=[user_id])


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

    # Lightweight, idempotent schema migration for existing installations.
    # The old code attempted ALTER TABLE on every startup and relied on caught
    # exceptions. That was noisy and could leave SQLite databases missing
    # columns. Inspect the actual schema first and use a dialect-safe type.
    inspector = db.inspect(db.engine)
    dialect = db.engine.dialect.name

    def add_column_if_missing(table_name, column_name, column_type):
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if column_name in columns:
            return
        db.session.execute(db.text(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        ))
        db.session.commit()
        inspector.clear_cache()

    blob_type = "BYTEA" if dialect == "postgresql" else "BLOB"
    add_column_if_missing("items", "pickup_location", "VARCHAR(200)")
    add_column_if_missing("items", "linked_lost_id", "INTEGER")
    add_column_if_missing("users", "profile_photo", blob_type)
    add_column_if_missing("users", "profile_photo_mime", "VARCHAR(50)")


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


def user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "error")
            return redirect(url_for("user_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


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


def notify(user_id, title, message, link=None):
    if user_id:
        db.session.add(Notification(user_id=user_id, title=title, message=message, link=link))


@app.route("/")
def home():
    if not session.get("user_id") and not session.get("admin_authenticated"):
        return render_template("entry.html")
    if session.get("admin_authenticated"):
        return redirect(url_for("admin"))
    q = clean(request.args.get("q"), 100)
    kind = clean(request.args.get("kind"), 20)
    category = clean(request.args.get("category"), 80)
    status = clean(request.args.get("status"), 30)
    query = Item.query
    if q:
        pattern = f"%{q}%"
        query = query.filter(db.or_(Item.title.ilike(pattern), Item.description.ilike(pattern), Item.location.ilike(pattern), Item.pickup_location.ilike(pattern)))
    if kind in ["Lost", "Found"]:
        query = query.filter_by(kind=kind)
    if category:
        query = query.filter_by(category=category)
    if status in ["Open", "Found Reported", "Claim in Progress", "Claimed"]:
        query = query.filter_by(status=status)
    items = query.order_by(Item.id.desc()).all()
    categories = [x[0] for x in db.session.query(Item.category).distinct().order_by(Item.category).all() if x[0]]
    lost = Item.query.filter_by(kind="Lost").count()
    found = Item.query.filter_by(kind="Found").count()
    feedback_count = Feedback.query.count()
    unread = Notification.query.filter_by(user_id=session.get("user_id"), is_read=False).count() if session.get("user_id") else 0
    return render_template("home.html", items=items, q=q, kind=kind, category=category, status=status, categories=categories, lost=lost, found=found, feedback_count=feedback_count, unread=unread)


@app.route("/report", methods=["GET", "POST"])
@user_required
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

        db.session.add(Item(title=title, kind=kind, category=category, location=location, reporter_id=session.get("user_id"),
                            pickup_location=pickup_location or None, description=description,
                            photo_data=photo_data, photo_mime=photo_mime))
        db.session.commit()
        flash("Item posted successfully!", "success")
        return redirect(url_for("home"))
    return render_template("report.html", selected_kind=clean(request.args.get("kind"), 20))


@app.route("/report-found/<int:lost_id>", methods=["GET", "POST"])
@user_required
def report_found(lost_id):
    """Let a user report a lost item as found directly from its card."""
    lost_item = db.session.get(Item, lost_id)
    if not lost_item or lost_item.kind != "Lost":
        flash("That lost report could not be found.", "error")
        return redirect(url_for("home"))

    if lost_item.status != "Open":
        flash("This lost report already has a found report or is no longer open.", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        found_location = clean(request.form.get("found_location"), 200)
        found_description = clean(request.form.get("description"), 2000)
        pickup_location = clean(request.form.get("pickup_location"), 200)

        if not found_location or not found_description:
            flash("Please add where you found it and a short description.", "error")
            return render_template("report_found.html", lost_item=lost_item)

        f = request.files.get("photo")
        photo_data = photo_mime = None
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED:
                flash("Use PNG, JPG, JPEG or WEBP only.", "error")
                return render_template("report_found.html", lost_item=lost_item)
            photo_data = f.read()
            if len(photo_data) > 5 * 1024 * 1024:
                flash("Photo must be 5 MB or smaller.", "error")
                return render_template("report_found.html", lost_item=lost_item)
            if not (f.mimetype or "").startswith("image/"):
                flash("Please upload a valid image.", "error")
                return render_template("report_found.html", lost_item=lost_item)
            photo_mime = f.mimetype

        found_item = Item(
            title=lost_item.title,
            kind="Found",
            category=lost_item.category,
            location=found_location,
            pickup_location=pickup_location or None,
            description=found_description,
            photo_data=photo_data,
            photo_mime=photo_mime,
            reporter_id=session.get("user_id"),
            linked_lost_id=lost_item.id
        )
        db.session.add(found_item)
        # Keep the lost report visible, but make it clear that someone has reported
        # a possible match so users do not submit the same found report repeatedly.
        lost_item.status = "Found Reported"
        if lost_item.reporter_id and lost_item.reporter_id != session.get("user_id"):
            notify(lost_item.reporter_id, "Your lost item may have been found", f"A found report was submitted for {lost_item.title}.", url_for("my_reports"))
        db.session.commit()
        flash("Great! Your found report is now visible to the person who lost it.", "success")
        return redirect(url_for("home"))

    return render_template("report_found.html", lost_item=lost_item)


@app.route("/feedback", methods=["GET", "POST"])
@user_required
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
@user_required
def claim(id):
    item = db.session.get(Item, id)
    uid = session["user_id"]
    if not item or item.kind != "Found" or item.status != "Open":
        flash("This item is not available for a new claim.", "error")
        return redirect(url_for("home"))
    if item.reporter_id == uid:
        flash("You cannot claim an item that you reported as found.", "error")
        return redirect(url_for("home"))
    existing = Claim.query.filter_by(item_id=id, user_id=uid).filter(Claim.status.in_(["Pending", "Approved"])).first()
    if existing:
        flash("You already have an active claim for this item.", "error")
        return redirect(url_for("my_reports"))
    if request.method == "POST":
        user = db.session.get(User, uid)
        proof = clean(request.form.get("proof"), 2000)
        if not proof:
            flash("Please provide ownership proof.", "error")
            return redirect(url_for("claim", id=id))
        claim_obj = Claim(item_id=id, user_id=user.id, student_name=user.name, roll_number=user.name, proof=proof)
        db.session.add(claim_obj)
        item.status = "Claim in Progress"
        notify(item.reporter_id, "A claim was submitted", f"Someone submitted a claim for {item.title}.", url_for("my_reports")) if item.reporter_id and item.reporter_id != uid else None
        db.session.commit()
        flash("Claim submitted. Waiting for admin approval.", "success")
        return redirect(url_for("my_reports"))
    return render_template("claim.html", item=item)

@app.route("/user/register", methods=["GET","POST"])
def user_register():
    if request.method == "POST":
        name=clean(request.form.get("name"),150); email=clean(request.form.get("email"),200).lower(); password=request.form.get("password","")
        if not name or "@" not in email or len(password)<8: flash("Enter a name, valid email, and password of at least 8 characters.","error")
        elif User.query.filter_by(email=email).first(): flash("An account with this email already exists.","error")
        else:
            u=User(name=name,email=email,password_hash=generate_password_hash(password)); db.session.add(u); db.session.commit(); session["user_id"]=u.id; session["user_name"]=u.name; flash("Account created.","success"); return redirect(url_for("my_reports"))
    return render_template("user_auth.html", mode="register")

@app.route("/user/login", methods=["GET","POST"])
def user_login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    if session.get("admin_authenticated"):
        return redirect(url_for("admin"))
    if request.method == "POST":
        u=User.query.filter_by(email=clean(request.form.get("email"),200).lower()).first(); password=request.form.get("password","")
        if u and check_password_hash(u.password_hash,password): session["user_id"]=u.id; session["user_name"]=u.name; return redirect(safe_next(request.form.get("next")) or url_for("my_reports"))
        flash("Invalid email or password.","error")
    return render_template("user_auth.html", mode="login", next=safe_next(request.values.get("next","")))


@app.route("/profile", methods=["GET", "POST"])
@user_required
def profile():
    user = db.session.get(User, session["user_id"])
    if request.method == "POST":
        f = request.files.get("profile_photo")
        if not f or not f.filename:
            flash("Please choose a profile picture.", "error")
            return redirect(url_for("profile"))
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED or not (f.mimetype or "").startswith("image/"):
            flash("Use PNG, JPG, JPEG or WEBP only.", "error")
            return redirect(url_for("profile"))
        data = f.read()
        if len(data) > 5 * 1024 * 1024:
            flash("Profile picture must be 5 MB or smaller.", "error")
            return redirect(url_for("profile"))
        user.profile_photo = data
        user.profile_photo_mime = f.mimetype
        db.session.commit()
        flash("Profile picture updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)


@app.get("/profile/photo/<int:user_id>")
@user_required
def profile_photo(user_id):
    user = db.session.get(User, user_id)
    if not user or not user.profile_photo:
        abort(404)
    return send_file(io.BytesIO(user.profile_photo), mimetype=user.profile_photo_mime or "image/jpeg", max_age=3600)

@app.post("/user/logout")
@user_required
def user_logout():
    session.pop("user_id",None); session.pop("user_name",None); flash("Logged out.","success"); return redirect(url_for("user_login"))

@app.get("/my-reports")
@user_required
def my_reports():
    uid=session["user_id"]
    reports=Item.query.filter_by(reporter_id=uid).order_by(Item.id.desc()).all()
    claims=Claim.query.filter_by(user_id=uid).order_by(Claim.id.desc()).all()
    notifications=Notification.query.filter_by(user_id=uid).order_by(Notification.id.desc()).limit(10).all()
    unread=Notification.query.filter_by(user_id=uid, is_read=False).count()
    return render_template("my_reports.html", reports=reports, claims=claims, notifications=notifications, unread=unread)

@app.post("/claim/<int:id>/confirm")
@user_required
def confirm_claim(id):
    c = db.session.get(Claim, id)
    if not c or c.user_id != session["user_id"] or c.status != "Approved" or c.user_confirmed:
        abort(403)
    c.user_confirmed = True
    c.item.status = "Claimed"
    if c.item.reporter_id and c.item.reporter_id != session["user_id"]:
        notify(c.item.reporter_id, "Claim completed", f"The claim for {c.item.title} has been confirmed.", url_for("my_reports"))
    db.session.commit()
    flash("You confirmed the claim. Pickup is now ready.", "success")
    return redirect(url_for("my_reports"))


@app.post("/claim/<int:id>/cancel")
@user_required
def cancel_claim(id):
    # Prevent an approved claim from permanently locking an item when the
    # claimant changes their mind or does not want to complete the handover.
    c = db.session.get(Claim, id)
    if not c or c.user_id != session["user_id"] or c.status not in {"Pending", "Approved"} or c.user_confirmed:
        abort(403)
    item = c.item
    c.status = "Cancelled"
    if item.status == "Claim in Progress":
        item.status = "Open"
    if item.reporter_id and item.reporter_id != session["user_id"]:
        notify(item.reporter_id, "Claim cancelled", f"The claim for {item.title} was cancelled and the item is available again.", url_for("home"))
    db.session.commit()
    flash("Claim cancelled. The item is available for another claim.", "success")
    return redirect(url_for("my_reports"))

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
    stats = {
        "lost": Item.query.filter_by(kind="Lost").count(),
        "found": Item.query.filter_by(kind="Found").count(),
        "pending": Claim.query.filter_by(status="Pending").count(),
        "claimed": Item.query.filter_by(status="Claimed").count(),
        "users": User.query.count(),
    }
    return render_template("admin.html", claims=claims, feedback=feedback, stats=stats)


@app.post("/admin/<int:id>/<action>")
@admin_required
def action(id, action):
    if action not in {"approve", "reject"}:
        abort(400)
    claim = db.session.get(Claim, id)
    if not claim:
        return redirect(url_for("admin"))
    if action == "approve":
        if claim.status != "Pending":
            return redirect(url_for("admin"))
        claim.status = "Approved"
        claim.item.status = "Claim in Progress"
        notify(claim.user_id, "Claim approved", f"Your claim for {claim.item.title} was approved. Confirm it in My Reports.", url_for("my_reports"))
    else:
        # Admin can reject either a pending claim or an approved claim that
        # has not been confirmed. This provides a recovery path instead of
        # leaving the item stuck in Claim in Progress forever.
        if claim.status not in {"Pending", "Approved"} or claim.user_confirmed:
            return redirect(url_for("admin"))
        claim.status = "Rejected"
        claim.item.status = "Open"
        notify(claim.user_id, "Claim rejected", f"Your claim for {claim.item.title} was rejected by the administrator.", url_for("home"))
    db.session.commit()
    flash(f"Claim {claim.status.lower()}.", "success")
    return redirect(url_for("admin"))


@app.get("/notifications/read")
@user_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=session["user_id"], is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(url_for("my_reports"))


@app.route("/uploads/<int:id>")
def uploads(id):
    if not session.get("user_id") and not session.get("admin_authenticated"):
        return redirect(url_for("user_login", next=request.path))
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
