import os
import io
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-secret")

# Local development uses SQLite. Online deployment uses DATABASE_URL
# (for example, a Supabase/Render PostgreSQL connection string).
database_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE, 'lostfound.db')}")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config.update(
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)

db = SQLAlchemy(app)
ALLOWED = {"png", "jpg", "jpeg", "webp"}

ADMIN_USERNAME = os.environ.get("CAMPUSFIND_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("CAMPUSFIND_ADMIN_PASSWORD", "CampusFind@2026")
ADMIN_PASSWORD_HASH = os.environ.get("CAMPUSFIND_ADMIN_PASSWORD_HASH", "")


class Item(db.Model):
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    location = db.Column(db.String(200), nullable=False)
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


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            flash("Please sign in as an administrator to access the admin portal.", "error")
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_password_ok(password):
    if ADMIN_PASSWORD_HASH:
        return check_password_hash(ADMIN_PASSWORD_HASH, password)
    return secrets.compare_digest(password, ADMIN_PASSWORD)


@app.route("/")
def home():
    q = request.args.get("q", "").strip()
    kind = request.args.get("kind", "").strip()

    query = Item.query
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            db.or_(
                Item.title.ilike(pattern),
                Item.description.ilike(pattern),
                Item.location.ilike(pattern),
            )
        )
    if kind in ["Lost", "Found"]:
        query = query.filter_by(kind=kind)

    items = query.order_by(Item.id.desc()).all()
    lost = Item.query.filter_by(kind="Lost").count()
    found = Item.query.filter_by(kind="Found").count()
    feedback_count = Feedback.query.count()
    return render_template(
        "home.html", items=items, q=q, kind=kind,
        lost=lost, found=found, feedback_count=feedback_count
    )


@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":
        f = request.files.get("photo")
        photo_data = None
        photo_mime = None

        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED:
                flash("Use PNG, JPG, JPEG or WEBP only", "error")
                return redirect("/report")
            photo_data = f.read()
            photo_mime = f.mimetype or f"image/{ext}"
            if len(photo_data) > 5 * 1024 * 1024:
                flash("Photo must be 5 MB or smaller.", "error")
                return redirect("/report")

        item = Item(
            title=request.form.get("title", "").strip(),
            kind=request.form.get("kind", "Lost"),
            category=request.form.get("category", "Other"),
            location=request.form.get("location", "").strip(),
            description=request.form.get("description", "").strip(),
            photo_data=photo_data,
            photo_mime=photo_mime,
        )
        if not item.title or not item.location or not item.description:
            flash("Please fill in all required fields.", "error")
            return redirect("/report")

        db.session.add(item)
        db.session.commit()
        flash("Item posted successfully! It is now stored in the online database.", "success")
        return redirect("/")
    return render_template("report.html")


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Anonymous"
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
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
        return redirect("/")

    if request.method == "POST":
        db.session.add(Claim(
            item_id=id,
            student_name=request.form.get("student_name", "").strip(),
            roll_number=request.form.get("roll_number", "").strip(),
            proof=request.form.get("proof", "").strip(),
        ))
        db.session.commit()
        flash("Claim submitted for verification!", "success")
        return redirect("/")

    return render_template("claim.html", item=item)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_authenticated"):
        return redirect(request.args.get("next") or url_for("admin"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USERNAME) and admin_password_ok(password):
            session.clear()
            session["admin_authenticated"] = True
            session["admin_username"] = username
            return redirect(request.form.get("next") or url_for("admin"))
        flash("Invalid admin username or password.", "error")

    return render_template("admin_login.html", next=request.args.get("next", ""))


@app.route("/admin/logout")
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
    if action not in ["approve", "reject"]:
        return redirect("/admin")

    claim = db.session.get(Claim, id)
    if not claim:
        return redirect("/admin")

    claim.status = "Approved" if action == "approve" else "Rejected"
    if action == "approve":
        claim.item.status = "Claimed"
    db.session.commit()
    return redirect("/admin")


@app.route("/uploads/<int:id>")
def uploads(id):
    item = db.session.get(Item, id)
    if not item or not item.photo_data:
        return ("", 404)
    return send_file(
        io.BytesIO(item.photo_data),
        mimetype=item.photo_mime or "application/octet-stream",
        download_name=f"campusfind-{item.id}",
    )


@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        return {"status": "error", "database": "unavailable"}, 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
