"""STUDIO 01 — Backend API.

Flask REST API with JWT authentication. The frontend is served
separately as static files (Netlify). Database: PostgreSQL (Neon) or SQLite for local dev.
"""
import os
import json
import hmac
import hashlib
import random
import secrets
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt,
)
from flask_cors import CORS

# ----- Optional dependencies (app still runs without them) -----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import razorpay
except Exception:
    razorpay = None

try:
    import cloudinary
    import cloudinary.uploader
except Exception:
    cloudinary = None

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    SENTRY_DSN = os.environ.get('SENTRY_DSN')
    if SENTRY_DSN:
        sentry_sdk.init(dsn=SENTRY_DSN, integrations=[FlaskIntegration()], traces_sample_rate=0.1)
except Exception:
    sentry_sdk = None


def maybe_capture_exception(exc):
    try:
        if 'sentry_sdk' in globals() and sentry_sdk is not None:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def maybe_capture_message(msg, level='error'):
    try:
        if 'sentry_sdk' in globals() and sentry_sdk is not None:
            sentry_sdk.capture_message(msg, level=level)
    except Exception:
        pass


# ============================================================
# CONFIG
# ============================================================
def _normalize_db_url(url):
    """Render/Heroku hand out postgres:// URLs; SQLAlchemy needs postgresql://."""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


IS_PRODUCTION = os.environ.get('FLASK_ENV') == 'production' or os.environ.get('PRODUCTION') == '1'

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = _normalize_db_url(os.environ.get('DATABASE_URL')) or 'sqlite:///cafe.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# JWT
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET') or os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
jwt = JWTManager(app)

db = SQLAlchemy(app)

# CORS: allow the configured frontend origin (defaults to * for local dev).
# Auth uses bearer tokens, not cookies, so credentials are not required.
FRONTEND_ORIGIN = os.environ.get('FRONTEND_ORIGIN', '*')
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGIN}, r"/health": {"origins": "*"}},
     supports_credentials=False)

try:
    from flask_migrate import Migrate
    migrate = Migrate(app, db)
except Exception:
    migrate = None

# Cloudinary
if cloudinary is not None:
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
        api_key=os.environ.get('CLOUDINARY_API_KEY', ''),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET', ''),
    )

# Razorpay
razorpay_key_id = os.environ.get('RAZORPAY_KEY_ID')
razorpay_key_secret = os.environ.get('RAZORPAY_KEY_SECRET')
razorpay_init_error = None
if razorpay is not None and razorpay_key_id and razorpay_key_secret:
    try:
        razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))
    except Exception as exc:
        razorpay_client = None
        razorpay_init_error = str(exc)
else:
    razorpay_client = None
    razorpay_init_error = 'Razorpay credentials are missing.' if not (razorpay_key_id and razorpay_key_secret) else None


# ============================================================
# DATABASE MODELS
# ============================================================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='Customer')
    coins = db.Column(db.Integer, default=0)
    orders = db.relationship('Order', backref='customer', lazy=True)
    reset_token = db.Column(db.String(100), nullable=True)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_order_date = db.Column(db.String(20), nullable=True)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    items = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)
    coins_used = db.Column(db.Integer, default=0)
    currency_paid = db.Column(db.Float, nullable=False)
    date_time = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    payment_id = db.Column(db.String(100), nullable=True)
    payment_method = db.Column(db.String(100), nullable=True)
    share_reward_claimed = db.Column(db.Boolean, default=False)


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(10), nullable=False)
    guests = db.Column(db.String(10), nullable=False)
    notes = db.Column(db.String(200), default='None')
    table_id = db.Column(db.Integer, db.ForeignKey('table.id'), nullable=True)
    status = db.Column(db.String(20), default='Confirmed')
    # Hard guarantee: one table cannot be booked twice for the same date+time.
    # (table_id NULL = general reservation with no specific table; NULLs don't collide.)
    __table_args__ = (db.UniqueConstraint('table_id', 'date', 'time', name='uq_table_slot'),)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    item_name = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.String(200), default="")


class ReferralCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class Special(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(150), nullable=False)
    discount = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=False)


class OrderAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    meta = db.Column(db.Text, nullable=True)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    items = db.relationship('MenuItem', backref='category', lazy=True)


class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), default="")
    image_url = db.Column(db.String(500), default="")
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    is_sold_out = db.Column(db.Boolean, default=False)


class Table(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_number = db.Column(db.String(10), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(20), default='indoor')  # indoor | outdoor | terrace
    is_available = db.Column(db.Boolean, default=True)


class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(200), default='')
    icon = db.Column(db.String(60), default='lucide:award')
    requirement_type = db.Column(db.String(30), nullable=False)  # order_count|total_spend|streak|early_bird|review_count
    requirement_value = db.Column(db.Float, default=0)


class UserBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badge.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'badge_id', name='uq_user_badge'),)


class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(500), nullable=False)
    caption = db.Column(db.String(200), default='')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), default='')
    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(10), nullable=False)
    duration_minutes = db.Column(db.Integer, default=60)
    capacity = db.Column(db.Integer, default=10)
    registered_count = db.Column(db.Integer, default=0)
    price = db.Column(db.Float, default=0)
    image_url = db.Column(db.String(500), default='')
    is_active = db.Column(db.Boolean, default=True)


class EventRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('event_id', 'user_id', name='uq_event_user'),)


class Offer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default='')
    offer_type = db.Column(db.String(20), default='percent')  # percent | flat | combo
    discount_value = db.Column(db.Float, default=0)
    combo_price = db.Column(db.Float, default=0)
    image_url = db.Column(db.String(500), default='')
    is_active = db.Column(db.Boolean, default=True)
    valid_from = db.Column(db.String(20), nullable=True)
    valid_until = db.Column(db.String(20), nullable=True)
    items = db.relationship('OfferItem', backref='offer', lazy=True, cascade='all, delete-orphan')


class OfferItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(db.Integer, db.ForeignKey('offer.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)


# ============================================================
# AUTH HELPERS
# ============================================================
def current_user_id():
    ident = get_jwt_identity()
    return int(ident) if ident is not None else None


def admin_required(fn):
    """JWT + Admin role. Single definition (fixes the old duplicate-decorator bug)."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if get_jwt().get('role') != 'Admin':
            return jsonify({'error': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper


def issue_tokens(user):
    claims = {'role': user.role, 'username': user.username}
    access = create_access_token(identity=str(user.id), additional_claims=claims)
    refresh = create_refresh_token(identity=str(user.id), additional_claims=claims)
    return access, refresh


def user_public(user):
    ref = ReferralCode.query.filter_by(owner_id=user.id).first()
    return {
        'id': user.id, 'username': user.username, 'email': user.email,
        'role': user.role, 'coins': user.coins, 'ref_code': ref.code if ref else '',
    }


# ============================================================
# DOMAIN HELPERS
# ============================================================
def calculate_coins(amount):
    return max(1, int(amount * random.uniform(0.05, 0.10)))


def get_redeemable_items():
    redeemable_cats = ['Beverages', 'Gourmet Sandwiches', 'Desserts']
    categories = Category.query.filter(Category.name.in_(redeemable_cats)).all()
    r = {}
    for cat in categories:
        for item in cat.items:
            r[item.name] = {'price': item.price, 'category': cat.name}
    return r


def send_order_email(order_obj, qr_url):
    """Send an HTML receipt with an inline QR (optional; no-op unless SMTP configured)."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage

    mail_host = os.environ.get('MAIL_SERVER')
    if not mail_host:
        return
    mail_port = int(os.environ.get('MAIL_PORT', 587))
    mail_user = os.environ.get('MAIL_USERNAME')
    mail_pass = os.environ.get('MAIL_PASSWORD')
    mail_from = os.environ.get('MAIL_FROM', 'no-reply@studio01.example')

    user = User.query.get(order_obj.user_id)
    if not user or not user.email:
        return

    msg = MIMEMultipart('related')
    msg['Subject'] = f"Your STUDIO 01 Order #{order_obj.order_id}"
    msg['From'] = mail_from
    msg['To'] = user.email

    try:
        items = json.loads(order_obj.items)
    except Exception:
        items = []
    items_html = ''.join(
        f"<li>{i.get('name')} — Qty: {i.get('quantity')} — ₹{i.get('price') * i.get('quantity')}</li>"
        for i in items
    )
    html = f"""
    <html><body style="font-family:Inter,Arial,sans-serif;color:#2C2420;">
      <h2>Thanks for your order, {user.username}!</h2>
      <p>Order <strong>#{order_obj.order_id}</strong> — <em>{order_obj.date_time}</em></p>
      <p><strong>Status:</strong> {order_obj.status}</p>
      <ul>{items_html}</ul>
      <p><strong>Total:</strong> ₹{order_obj.total}</p>
      <p><img src="{qr_url}" alt="Bill QR" width="240"/></p>
      <p style="font-size:0.85rem;color:#8B7D72">STUDIO 01</p>
    </body></html>
    """
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(f"Order #{order_obj.order_id} — Total Rs.{order_obj.total}", 'plain'))
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    try:
        with smtplib.SMTP(mail_host, mail_port, timeout=10) as s:
            s.starttls()
            if mail_user and mail_pass:
                s.login(mail_user, mail_pass)
            s.send_message(msg)
    except Exception as e:
        maybe_capture_exception(e)


# ============================================================
# ERROR HANDLERS & SECURITY HEADERS
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Server error"}), 500


@app.after_request
def set_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'no-referrer-when-downgrade')
    return response


# ============================================================
# HEALTH & CONFIG
# ============================================================
@app.route('/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


@app.route('/api/config')
def get_config():
    key_id = os.environ.get('RAZORPAY_KEY_ID', '')
    configured = bool(key_id and os.environ.get('RAZORPAY_KEY_SECRET'))
    return jsonify({"razorpay_key": key_id, "razorpay_available": configured})


# ============================================================
# AUTH ROUTES
# ============================================================
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    ref_code = (data.get('referral_code') or '').strip()

    if not username or not email or not password:
        return jsonify({'success': False, 'message': 'Username, email, and password are required.'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': 'Username taken.'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered.'}), 409

    new_user = User(username=username, email=email, password=generate_password_hash(password))
    db.session.add(new_user)
    db.session.flush()

    if ref_code:
        ref = ReferralCode.query.filter(db.func.lower(ReferralCode.code) == ref_code.lower()).first()
        if ref and ref.owner_id != new_user.id:
            owner = User.query.get(ref.owner_id)
            if owner:
                owner.coins += 50
            new_user.coins += 50

    # Referral code mirrors the username as typed (capped to the column length).
    db.session.add(ReferralCode(code=username[:10], owner_id=new_user.id))
    db.session.commit()

    access, refresh = issue_tokens(new_user)
    return jsonify({'success': True, 'access_token': access, 'refresh_token': refresh,
                    'user': user_public(new_user)}), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(username=(data.get('username') or '').strip()).first()
    if user and check_password_hash(user.password, data.get('password') or ''):
        access, refresh = issue_tokens(user)
        return jsonify({'success': True, 'access_token': access, 'refresh_token': refresh,
                        'user': user_public(user)})
    return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401


@app.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    uid = current_user_id()
    user = User.query.get(uid)
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404
    access = create_access_token(identity=str(user.id),
                                 additional_claims={'role': user.role, 'username': user.username})
    return jsonify({'success': True, 'access_token': access})


@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=(data.get('email') or '').strip()).first()
    if user:
        token = secrets.token_urlsafe(16)
        user.reset_token = token
        db.session.commit()
        print(f"\n[RESET TOKEN FOR {user.username}]: {token}\n")
    # Generic response either way (do not reveal whether the email exists)
    return jsonify({'success': True,
                    'message': 'If an account exists, a reset token has been issued.'})


@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    password = data.get('password') or ''
    if not token or not password:
        return jsonify({'success': False, 'message': 'Token and password required.'}), 400
    user = User.query.filter_by(reset_token=token).first()
    if not user:
        return jsonify({'success': False, 'message': 'Invalid or expired token.'}), 400
    user.password = generate_password_hash(password)
    user.reset_token = None
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password reset successfully.'})


@app.route('/api/auth/change-password', methods=['POST'])
@jwt_required()
def change_password():
    data = request.get_json(silent=True) or {}
    user = User.query.get(current_user_id())
    if not user or not check_password_hash(user.password, data.get('current_password') or ''):
        return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 400
    new_password = data.get('new_password') or ''
    if len(new_password) < 4:
        return jsonify({'success': False, 'message': 'New password is too short.'}), 400
    user.password = generate_password_hash(new_password)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password changed successfully.'})


# ============================================================
# PUBLIC MENU ROUTES
# ============================================================
@app.route('/api/menu')
def api_menu():
    categories = Category.query.all()
    menu_dict = {}
    for cat in categories:
        menu_dict[cat.name] = {
            item.name: {
                "price": item.price, "description": item.description,
                "image_url": item.image_url, "sold_out": item.is_sold_out,
            } for item in cat.items
        }
    customizations = {
        "Beverages": [{"name": "Extra Shot", "price": 50}, {"name": "Oat Milk", "price": 40},
                      {"name": "Sugar-Free", "price": 0}, {"name": "Less Ice", "price": 0}],
        "Desserts": [{"name": "Whipped Cream", "price": 30}, {"name": "Caramel Drizzle", "price": 20}],
    }
    return jsonify({"menu": menu_dict, "customizations": customizations})


@app.route('/api/redeemable-items')
def api_redeemable():
    return jsonify(get_redeemable_items())


@app.route('/api/special')
def api_special():
    s = Special.query.filter_by(active=True).first()
    if not s:
        return jsonify({"active": False})
    return jsonify({"active": True, "item": s.item, "discount": s.discount})


@app.route('/api/soldout')
def api_soldout():
    items = MenuItem.query.filter_by(is_sold_out=True).with_entities(MenuItem.name).all()
    return jsonify([i[0] for i in items])


@app.route('/api/reviews')
def api_reviews():
    reviews = Review.query.all()
    res = {}
    for r in reviews:
        res.setdefault(r.item_name, {"total": 0, "count": 0})
        res[r.item_name]["total"] += r.rating
        res[r.item_name]["count"] += 1
    return jsonify({item: round(d["total"] / d["count"], 1) for item, d in res.items()})


# ============================================================
# CUSTOMER ROUTES (JWT)
# ============================================================
@app.route('/api/user/profile')
@jwt_required()
def api_user_profile():
    user = User.query.get(current_user_id())
    if not user:
        return jsonify({'error': 'User not found'}), 404
    data = user_public(user)
    data['current_streak'] = user.current_streak or 0
    data['longest_streak'] = user.longest_streak or 0
    data['badges'] = badges_payload(user)
    return jsonify(data)


@app.route('/api/user/orders')
@jwt_required()
def api_user_orders():
    orders = Order.query.filter_by(user_id=current_user_id()).order_by(Order.id.desc()).all()
    return jsonify([{
        "id": o.id, "order_id": o.order_id, "items": json.loads(o.items), "total": o.total,
        "coins_used": o.coins_used, "currency_paid": o.currency_paid, "date_time": o.date_time,
        "status": o.status,
    } for o in orders])


@app.route('/api/user/orders/<int:oid>/review', methods=['POST'])
@jwt_required()
def submit_review(oid):
    data = request.get_json(silent=True) or {}
    if not data.get('item') or not data.get('rating'):
        return jsonify({'success': False, 'message': 'Item and rating required.'}), 400
    rev = Review(user_id=current_user_id(), item_name=data['item'],
                 rating=int(data['rating']), comment=(data.get('comment') or '')[:200])
    db.session.add(rev)
    db.session.commit()
    return jsonify({"success": True})


@app.route('/api/create-razorpay-order', methods=['POST'])
@jwt_required()
def create_razorpay_order():
    data = request.get_json(silent=True) or {}
    total = data.get('total', 0)
    coins_to_use = data.get('coins_to_use', 0)
    currency_paid = max(0, total - coins_to_use)
    payment_amount = int(currency_paid * 100)

    if payment_amount <= 0:
        return jsonify({"id": "free_order", "amount": 0, "currency": "INR"})
    if razorpay_client is None:
        return jsonify({"id": "mock_order", "amount": payment_amount, "currency": "INR",
                        "note": "razorpay_unavailable", "message": "Online payment could not be initialized.",
                        "details": razorpay_init_error or "No Razorpay client available."})
    try:
        order = razorpay_client.order.create(
            {'amount': payment_amount, 'currency': 'INR', 'payment_capture': '1'})
        return jsonify(order)
    except Exception as exc:
        maybe_capture_exception(exc)
        return jsonify({"note": "razorpay_unavailable", "message": "Failed to connect to Razorpay.",
                        "details": str(exc)}), 502


def verify_razorpay_signature(order_id, payment_id, signature):
    """Razorpay Standard Checkout signature check: HMAC-SHA256(order_id|payment_id, KEY_SECRET)."""
    secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
    if not (secret and order_id and payment_id and signature):
        return False
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


@app.route('/api/verify-payment', methods=['POST'])
@jwt_required()
def verify_payment():
    data = request.get_json(silent=True) or {}
    order_id = data.get('razorpay_order_id')
    payment_id = data.get('razorpay_payment_id')
    signature = data.get('razorpay_signature')
    if not (order_id and payment_id and signature):
        return jsonify({'success': False, 'message': 'Missing payment fields.'}), 400
    if not verify_razorpay_signature(order_id, payment_id, signature):
        return jsonify({'success': False, 'message': 'Payment signature verification failed.'}), 400
    return jsonify({'success': True})


@app.route('/api/order', methods=['POST'])
@jwt_required()
def api_order():
    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    total = data.get('total', 0)
    coins_to_use = data.get('coins_to_use', 0)
    payment_id = data.get('payment_id')
    payment_method = data.get('payment_method')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    user_id = current_user_id()

    # A claimed online payment must pass server-side signature verification before we mark it Paid.
    if payment_id:
        if not verify_razorpay_signature(razorpay_order_id, payment_id, razorpay_signature):
            return jsonify({'success': False, 'message': 'Payment could not be verified.'}), 400

    try:
        if coins_to_use > 0:
            user = User.query.get(user_id)
            if coins_to_use > user.coins:
                return jsonify({'success': False, 'message': 'Not enough coins'}), 400
            redeemable = get_redeemable_items()
            for i in items:
                base_name = i['name'].split(' [')[0]
                if base_name not in redeemable:
                    return jsonify({'success': False, 'message': f'Cannot use coins for {base_name}'}), 400

        currency_paid = max(0, total - coins_to_use)
        max_id = db.session.query(db.func.max(Order.order_id)).scalar()
        order_id = (max_id or 0) + 1
        time_now = datetime.now().strftime("%d-%m-%Y %I:%M %p")

        bill_text = (f"STUDIO 01\nOrder {order_id}\n{time_now}\n\n" +
                     "\n".join(f"{i['name']} X {i['quantity']} = {i['price'] * i['quantity']}" for i in items) +
                     f"\n\nPaid: Rs.{currency_paid}" + (f" + {coins_to_use} Coins" if coins_to_use else "") +
                     f"\nTotal: Rs.{total}")
        bill_qr_url = f"https://quickchart.io/qr?text={quote(bill_text)}&size=300&color=1C1410&bgcolor=FAF7F2"

        status = 'Paid' if payment_id else 'Pending'
        new_order = Order(order_id=order_id, user_id=user_id, items=json.dumps(items), total=total,
                          coins_used=coins_to_use, currency_paid=currency_paid, date_time=time_now,
                          payment_id=payment_id, payment_method=payment_method, status=status)
        db.session.add(new_order)

        user = User.query.get(user_id)
        user.coins -= coins_to_use
        coins_earned = calculate_coins(currency_paid)
        user.coins += coins_earned
        update_streak(user)
        db.session.commit()

        # Gamification: evaluate badges now that the order is persisted.
        new_badges = evaluate_and_award_badges(user)
        new_coin_balance = user.coins

        try:
            send_order_email(new_order, bill_qr_url)
        except Exception as ee:
            maybe_capture_exception(ee)

        resp = {"order_id": order_id, "total": total, "currency_paid": currency_paid,
                "coins_used": coins_to_use, "date_time": time_now, "coins_earned": coins_earned,
                "new_coin_balance": new_coin_balance, "bill_qr_url": bill_qr_url,
                "payment_method": payment_method, "new_badges": new_badges}
        if not payment_id:
            resp['offline_payment'] = True
        return jsonify(resp)
    except Exception as exc:
        maybe_capture_exception(exc)
        return jsonify({'success': False, 'message': 'Server error while creating order'}), 500


@app.route('/api/book', methods=['POST'])
@jwt_required(optional=True)
def api_book():
    d = request.get_json(silent=True) or {}
    if not d.get('name') or not d.get('email') or not d.get('date') or not d.get('time') or not d.get('guests'):
        return jsonify({'success': False, 'message': 'Missing required fields.'}), 400
    table_id = d.get('table_id') or None
    if table_id:
        table = Table.query.get(table_id)
        if not table or not table.is_available:
            return jsonify({'success': False, 'message': 'That table is not available.'}), 400
        # Pre-check the 90-minute window for this specific table.
        if table_id in _conflicting_table_ids(d.get('date'), d.get('time')):
            return jsonify({'success': False,
                            'message': 'Sorry, that table was just booked for this time. Please pick another.'}), 409
    reservation = Reservation(user_id=current_user_id(), name=d.get('name'), email=d.get('email'),
                              date=d.get('date'), time=d.get('time'), guests=d.get('guests'),
                              notes=d.get('notes', 'None'), table_id=table_id)
    db.session.add(reservation)
    try:
        db.session.commit()
    except IntegrityError:
        # Race condition: someone claimed the exact slot between our check and commit.
        db.session.rollback()
        return jsonify({'success': False,
                        'message': 'Sorry, that table was just booked. Please pick another.'}), 409
    return jsonify({'success': True})


# ============================================================
# ADMIN ROUTES (JWT + Admin role)
# ============================================================
@app.route('/api/admin/orders')
@admin_required
def api_admin_orders():
    orders = Order.query.order_by(Order.id.desc()).all()
    return jsonify([{
        "order_id": o.order_id,
        "customer_name": (User.query.get(o.user_id).username if o.user_id and User.query.get(o.user_id) else "Guest"),
        "items": json.loads(o.items), "total": o.total, "currency_paid": o.currency_paid,
        "date_time": o.date_time, "status": o.status, "payment_id": o.payment_id,
        "payment_method": o.payment_method,
    } for o in orders])


@app.route('/api/admin/update-order-status', methods=['POST'])
@admin_required
def update_status():
    data = request.get_json(silent=True) or {}
    o = Order.query.filter_by(order_id=data.get('order_id')).first()
    if o:
        o.status = data.get('status')
        db.session.commit()
    return jsonify({"success": True})


@app.route('/api/admin/mark-paid', methods=['POST'])
@admin_required
def admin_mark_paid():
    data = request.get_json(silent=True) or {}
    oid = data.get('order_id')
    o = Order.query.filter_by(order_id=oid).first()
    if not o:
        return jsonify({'success': False, 'error': 'order not found'}), 404
    o.payment_id = data.get('payment_id') or f"offline-{int(datetime.utcnow().timestamp())}"
    o.status = 'Paid'
    db.session.commit()

    try:
        audit = OrderAudit(order_id=oid, admin_id=current_user_id(), action='mark_paid',
                           meta=json.dumps({'payment_id': o.payment_id}))
        db.session.add(audit)
        db.session.commit()
    except Exception as exc:
        maybe_capture_exception(exc)

    try:
        items = json.loads(o.items)
        bill_text = (f"STUDIO 01\nOrder {o.order_id}\n{o.date_time}\n\n" +
                     "\n".join(f"{i.get('name')} X {i.get('quantity')} = {i.get('price') * i.get('quantity')}" for i in items) +
                     f"\n\nPaid: Rs.{o.currency_paid}\nTotal: Rs.{o.total}")
        bill_qr_url = f"https://quickchart.io/qr?text={quote(bill_text)}&size=300&color=1C1410&bgcolor=FAF7F2"
        send_order_email(o, bill_qr_url)
    except Exception as exc:
        maybe_capture_exception(exc)

    return jsonify({'success': True})


@app.route('/api/admin/reservations')
@admin_required
def api_admin_reservations():
    out = []
    for r in Reservation.query.order_by(Reservation.id.desc()).all():
        t = Table.query.get(r.table_id) if r.table_id else None
        out.append({"name": r.name, "email": r.email, "date": r.date, "time": r.time,
                    "guests": r.guests, "notes": r.notes, "status": r.status,
                    "table": (t.table_number if t else None),
                    "table_location": (t.location if t else None)})
    return jsonify(out)


@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    orders = Order.query.filter_by(status='Completed').all()
    revenue = {}
    for o in orders:
        day = o.date_time.split()[0]
        revenue[day] = revenue.get(day, 0) + o.currency_paid
    return jsonify(revenue)


@app.route('/api/admin/audits')
@admin_required
def api_admin_audits():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))
    q = OrderAudit.query.order_by(OrderAudit.timestamp.desc())
    total = q.count()
    audits = q.offset((page - 1) * per_page).limit(per_page).all()
    rows = []
    for a in audits:
        admin = User.query.get(a.admin_id) if a.admin_id else None
        rows.append({'order_id': a.order_id, 'admin': admin.username if admin else 'system',
                     'action': a.action, 'timestamp': a.timestamp.isoformat(),
                     'meta': json.loads(a.meta) if a.meta else {}})
    return jsonify({'total': total, 'page': page, 'per_page': per_page, 'audits': rows})


@app.route('/api/admin/special', methods=['POST'])
@admin_required
def admin_set_special():
    data = request.get_json(silent=True) or {}
    item = data.get('item')
    try:
        discount = int(data.get('discount', 0))
    except Exception:
        discount = 0
    if not item:
        return jsonify({'success': False, 'error': 'item required'}), 400
    Special.query.update({Special.active: False})
    db.session.add(Special(item=item, discount=discount, active=True))
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/toggle-soldout', methods=['POST'])
@admin_required
def toggle_soldout():
    data = request.get_json(silent=True) or {}
    item = MenuItem.query.filter_by(name=data.get('item')).first()
    if item:
        item.is_sold_out = not item.is_sold_out
        db.session.commit()
    return jsonify({"success": True})


MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


@app.route('/api/admin/upload-image', methods=['POST'])
@admin_required
def upload_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    if not (file.mimetype or '').startswith('image/'):
        return jsonify({"error": "Only image files are allowed."}), 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_IMAGE_BYTES:
        return jsonify({"error": "Image too large (max 5MB)."}), 400
    if cloudinary is None:
        return jsonify({"error": "Image upload is not configured. Paste an image URL instead."}), 501
    upload_result = cloudinary.uploader.upload(file, folder="cafe_menu")
    return jsonify({"url": upload_result.get('secure_url')})


# ============================================================
# ADMIN MENU MANAGEMENT (categories + items)
# ============================================================
def _menu_item_dict(item):
    return {
        'id': item.id, 'name': item.name, 'price': item.price,
        'description': item.description, 'image_url': item.image_url,
        'category_id': item.category_id,
        'category': item.category.name if item.category else None,
        'is_sold_out': item.is_sold_out,
    }


@app.route('/api/admin/categories', methods=['GET'])
@admin_required
def admin_list_categories():
    return jsonify([{'id': c.id, 'name': c.name} for c in Category.query.order_by(Category.name).all()])


@app.route('/api/admin/categories', methods=['POST'])
@admin_required
def admin_create_category():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Category name required.'}), 400
    if Category.query.filter_by(name=name).first():
        return jsonify({'success': False, 'message': 'Category already exists.'}), 409
    cat = Category(name=name)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'success': True, 'id': cat.id, 'name': cat.name}), 201


@app.route('/api/admin/menu-items', methods=['GET'])
@admin_required
def admin_list_menu_items():
    items = MenuItem.query.order_by(MenuItem.category_id, MenuItem.name).all()
    return jsonify([_menu_item_dict(i) for i in items])


@app.route('/api/admin/menu-items', methods=['POST'])
@admin_required
def admin_create_menu_item():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    category_id = data.get('category_id')
    # Allow specifying a category by name; create it if new.
    if not category_id and (data.get('category') or '').strip():
        cname = data['category'].strip()
        cat = Category.query.filter_by(name=cname).first()
        if not cat:
            cat = Category(name=cname)
            db.session.add(cat)
            db.session.flush()
        category_id = cat.id
    if not name or not category_id:
        return jsonify({'success': False, 'message': 'Name and category are required.'}), 400
    if not Category.query.get(category_id):
        return jsonify({'success': False, 'message': 'Invalid category.'}), 400
    try:
        price = float(data.get('price', 0))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid price.'}), 400
    item = MenuItem(name=name, price=price, description=(data.get('description') or '')[:200],
                    image_url=(data.get('image_url') or ''), category_id=category_id)
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'item': _menu_item_dict(item)}), 201


@app.route('/api/admin/menu-items/<int:item_id>', methods=['PUT', 'PATCH'])
@admin_required
def admin_update_menu_item(item_id):
    item = MenuItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': 'Item not found.'}), 404
    data = request.get_json(silent=True) or {}
    if (data.get('name') or '').strip():
        item.name = data['name'].strip()
    if 'price' in data:
        try:
            item.price = float(data['price'])
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Invalid price.'}), 400
    if 'description' in data:
        item.description = (data.get('description') or '')[:200]
    if 'image_url' in data:
        item.image_url = data.get('image_url') or ''
    if data.get('category_id') and Category.query.get(data['category_id']):
        item.category_id = data['category_id']
    db.session.commit()
    return jsonify({'success': True, 'item': _menu_item_dict(item)})


@app.route('/api/admin/menu-items/<int:item_id>', methods=['DELETE'])
@admin_required
def admin_delete_menu_item(item_id):
    item = MenuItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': 'Item not found.'}), 404
    # Safe cleanup: deactivate the Special if it referenced this item.
    # (Historical orders/reviews reference item names as snapshots and are untouched.)
    Special.query.filter_by(item=item.name).update({Special.active: False})
    _cleanup_offer_refs_for_item(item.id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})


def _cleanup_offer_refs_for_item(item_id):
    """Remove OfferItem references to a deleted item. No-op until Offers (Task 9) exist."""
    OfferItemModel = globals().get('OfferItem')
    if OfferItemModel is not None:
        OfferItemModel.query.filter_by(menu_item_id=item_id).delete()


# ============================================================
# GAMIFICATION (streaks + badges)
# ============================================================
def update_streak(user):
    today = datetime.now().date()
    last = None
    if user.last_order_date:
        try:
            last = datetime.strptime(user.last_order_date, "%Y-%m-%d").date()
        except Exception:
            last = None
    if last == today:
        pass  # already counted today
    elif last == today - timedelta(days=1):
        user.current_streak = (user.current_streak or 0) + 1
    else:
        user.current_streak = 1
    user.last_order_date = today.strftime("%Y-%m-%d")
    if (user.current_streak or 0) > (user.longest_streak or 0):
        user.longest_streak = user.current_streak


def _user_stats(user):
    orders = Order.query.filter_by(user_id=user.id).all()
    early = False
    for o in orders:
        try:
            if datetime.strptime(o.date_time, "%d-%m-%Y %I:%M %p").hour < 9:
                early = True
                break
        except Exception:
            pass
    return {
        'order_count': len(orders),
        'total_spend': sum(o.currency_paid for o in orders),
        'review_count': Review.query.filter_by(user_id=user.id).count(),
        'streak': user.current_streak or 0,
        'early_bird': early,
    }


def evaluate_and_award_badges(user):
    stats = _user_stats(user)
    earned_ids = {ub.badge_id for ub in UserBadge.query.filter_by(user_id=user.id).all()}
    newly = []
    for badge in Badge.query.all():
        if badge.id in earned_ids:
            continue
        rt, rv = badge.requirement_type, badge.requirement_value
        met = ((rt == 'order_count' and stats['order_count'] >= rv) or
               (rt == 'total_spend' and stats['total_spend'] >= rv) or
               (rt == 'streak' and stats['streak'] >= rv) or
               (rt == 'review_count' and stats['review_count'] >= rv) or
               (rt == 'early_bird' and stats['early_bird']))
        if met:
            db.session.add(UserBadge(user_id=user.id, badge_id=badge.id))
            newly.append({'key': badge.key, 'name': badge.name, 'icon': badge.icon,
                          'description': badge.description})
    if newly:
        db.session.commit()
    return newly


def badges_payload(user):
    earned = {ub.badge_id: ub.earned_at for ub in UserBadge.query.filter_by(user_id=user.id).all()}
    out = []
    for b in Badge.query.all():
        out.append({'key': b.key, 'name': b.name, 'description': b.description, 'icon': b.icon,
                    'earned': b.id in earned,
                    'earned_at': earned[b.id].isoformat() if b.id in earned else None})
    return out


# ============================================================
# RESERVATIONS — TABLES
# ============================================================
def _parse_time(t):
    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(t, fmt)
        except Exception:
            continue
    return None


def _conflicting_table_ids(date, time, window_minutes=90):
    req = _parse_time(time)
    conflicts = set()
    for r in Reservation.query.filter_by(date=date).all():
        if not r.table_id:
            continue
        rt = _parse_time(r.time)
        if req is None or rt is None or abs((req - rt).total_seconds()) < window_minutes * 60:
            conflicts.add(r.table_id)
    return conflicts


@app.route('/api/tables')
def api_tables():
    date = request.args.get('date')
    time = request.args.get('time')
    booked = _conflicting_table_ids(date, time) if date and time else set()
    tables = Table.query.order_by(Table.table_number).all()
    return jsonify([{'id': t.id, 'table_number': t.table_number, 'capacity': t.capacity,
                     'location': t.location,
                     'available': bool(t.is_available and t.id not in booked)} for t in tables])


@app.route('/api/admin/tables', methods=['GET'])
@admin_required
def admin_list_tables():
    return jsonify([{'id': t.id, 'table_number': t.table_number, 'capacity': t.capacity,
                     'location': t.location, 'is_available': t.is_available}
                    for t in Table.query.order_by(Table.table_number).all()])


@app.route('/api/admin/tables', methods=['POST'])
@admin_required
def admin_create_table():
    d = request.get_json(silent=True) or {}
    num = (d.get('table_number') or '').strip()
    if not num:
        return jsonify({'success': False, 'message': 'Table number required.'}), 400
    if Table.query.filter_by(table_number=num).first():
        return jsonify({'success': False, 'message': 'Table number already exists.'}), 409
    try:
        cap = int(d.get('capacity', 2))
    except (TypeError, ValueError):
        cap = 2
    t = Table(table_number=num, capacity=cap, location=d.get('location', 'indoor'), is_available=True)
    db.session.add(t)
    db.session.commit()
    return jsonify({'success': True, 'id': t.id}), 201


@app.route('/api/admin/tables/<int:tid>', methods=['PATCH'])
@admin_required
def admin_toggle_table(tid):
    t = Table.query.get(tid)
    if not t:
        return jsonify({'success': False, 'message': 'not found'}), 404
    d = request.get_json(silent=True) or {}
    if 'is_available' in d:
        t.is_available = bool(d['is_available'])
    db.session.commit()
    return jsonify({'success': True, 'is_available': t.is_available})


@app.route('/api/admin/tables/<int:tid>', methods=['DELETE'])
@admin_required
def admin_delete_table(tid):
    t = Table.query.get(tid)
    if t:
        db.session.delete(t)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# RECOMMENDATIONS
# ============================================================
@app.route('/api/recommendations')
@jwt_required(optional=True)
def api_recommendations():
    from collections import Counter
    sold_out = {i.name for i in MenuItem.query.filter_by(is_sold_out=True).all()}
    pop = Counter()
    for o in Order.query.all():
        try:
            for it in json.loads(o.items):
                pop[it['name'].split(' [')[0]] += it.get('quantity', 1)
        except Exception:
            pass
    uid = current_user_id()
    fav_items, fav_cats = Counter(), Counter()
    if uid:
        for o in Order.query.filter_by(user_id=uid).all():
            try:
                for it in json.loads(o.items):
                    base = it['name'].split(' [')[0]
                    fav_items[base] += it.get('quantity', 1)
                    mi = MenuItem.query.filter_by(name=base).first()
                    if mi and mi.category:
                        fav_cats[mi.category.name] += it.get('quantity', 1)
            except Exception:
                pass
    scored = []
    for mi in MenuItem.query.all():
        if mi.name in sold_out:
            continue
        score = pop.get(mi.name, 0)
        if uid:
            score += fav_items.get(mi.name, 0) * 3
            if mi.category:
                score += fav_cats.get(mi.category.name, 0) * 1.5
        scored.append((score, mi))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [mi for _, mi in scored[:6]]
    return jsonify([{'name': m.name, 'price': m.price, 'description': m.description,
                     'image_url': m.image_url, 'category': m.category.name if m.category else ''} for m in top])


# ============================================================
# SOCIAL — PHOTOS + SHARE & EARN
# ============================================================
@app.route('/api/photos')
def api_photos():
    photos = Photo.query.order_by(Photo.id.desc()).limit(30).all()
    return jsonify([{'id': p.id, 'image_url': p.image_url, 'caption': p.caption} for p in photos])


@app.route('/api/admin/photos', methods=['POST'])
@admin_required
def admin_add_photo():
    d = request.get_json(silent=True) or {}
    if not d.get('image_url'):
        return jsonify({'success': False, 'message': 'image_url required'}), 400
    p = Photo(image_url=d['image_url'], caption=(d.get('caption') or '')[:200], user_id=current_user_id())
    db.session.add(p)
    db.session.commit()
    return jsonify({'success': True, 'id': p.id}), 201


@app.route('/api/admin/photos/<int:pid>', methods=['DELETE'])
@admin_required
def admin_delete_photo(pid):
    p = Photo.query.get(pid)
    if p:
        db.session.delete(p)
        db.session.commit()
    return jsonify({'success': True})


@app.route('/api/user/orders/<int:oid>/share', methods=['POST'])
@jwt_required()
def share_order(oid):
    order = Order.query.filter_by(order_id=oid, user_id=current_user_id()).first()
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404
    if order.share_reward_claimed:
        return jsonify({'success': True, 'already': True, 'coins_awarded': 0, 'message': 'Reward already claimed.'})
    order.share_reward_claimed = True
    user = User.query.get(current_user_id())
    user.coins += 10
    db.session.commit()
    return jsonify({'success': True, 'coins_awarded': 10, 'new_coin_balance': user.coins})


# ============================================================
# EVENTS & WORKSHOPS
# ============================================================
def _event_dict(e):
    return {'id': e.id, 'title': e.title, 'description': e.description, 'date': e.date, 'time': e.time,
            'duration_minutes': e.duration_minutes, 'capacity': e.capacity,
            'registered_count': e.registered_count, 'price': e.price, 'image_url': e.image_url,
            'is_active': e.is_active, 'is_sold_out': e.registered_count >= e.capacity}


@app.route('/api/events')
def api_events():
    events = Event.query.filter_by(is_active=True).order_by(Event.date).all()
    return jsonify([_event_dict(e) for e in events])


@app.route('/api/events/<int:eid>/register', methods=['POST'])
@jwt_required()
def register_event(eid):
    event = Event.query.get(eid)
    if not event or not event.is_active:
        return jsonify({'success': False, 'message': 'Event not found'}), 404
    if event.registered_count >= event.capacity:
        return jsonify({'success': False, 'message': 'Event is sold out.'}), 409
    uid = current_user_id()
    if EventRegistration.query.filter_by(event_id=eid, user_id=uid).first():
        return jsonify({'success': False, 'message': 'You are already registered.'}), 409
    db.session.add(EventRegistration(event_id=eid, user_id=uid))
    event.registered_count += 1
    db.session.commit()
    return jsonify({'success': True, 'registered_count': event.registered_count})


@app.route('/api/admin/events', methods=['GET'])
@admin_required
def admin_list_events():
    return jsonify([_event_dict(e) for e in Event.query.order_by(Event.date).all()])


@app.route('/api/admin/events', methods=['POST'])
@admin_required
def admin_create_event():
    d = request.get_json(silent=True) or {}
    if not d.get('title') or not d.get('date') or not d.get('time'):
        return jsonify({'success': False, 'message': 'title, date, and time are required.'}), 400
    e = Event(title=d['title'], description=d.get('description', ''), date=d['date'], time=d['time'],
              duration_minutes=int(d.get('duration_minutes', 60) or 60), capacity=int(d.get('capacity', 10) or 10),
              price=float(d.get('price', 0) or 0), image_url=d.get('image_url', ''), is_active=True)
    db.session.add(e)
    db.session.commit()
    return jsonify({'success': True, 'id': e.id}), 201


@app.route('/api/admin/events/<int:eid>', methods=['PUT', 'PATCH'])
@admin_required
def admin_update_event(eid):
    e = Event.query.get(eid)
    if not e:
        return jsonify({'success': False, 'message': 'not found'}), 404
    d = request.get_json(silent=True) or {}
    for f in ['title', 'description', 'date', 'time', 'image_url']:
        if f in d:
            setattr(e, f, d[f])
    for f in ['duration_minutes', 'capacity']:
        if f in d:
            try:
                setattr(e, f, int(d[f]))
            except (TypeError, ValueError):
                pass
    if 'price' in d:
        try:
            e.price = float(d['price'])
        except (TypeError, ValueError):
            pass
    if 'is_active' in d:
        e.is_active = bool(d['is_active'])
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/events/<int:eid>', methods=['DELETE'])
@admin_required
def admin_delete_event(eid):
    e = Event.query.get(eid)
    if e:
        EventRegistration.query.filter_by(event_id=eid).delete()
        db.session.delete(e)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# OFFERS / MEAL DEALS
# ============================================================
def _offer_dict(o):
    names = []
    for oi in o.items:
        mi = MenuItem.query.get(oi.menu_item_id)
        if mi:
            names.append(mi.name)
    return {'id': o.id, 'title': o.title, 'description': o.description, 'offer_type': o.offer_type,
            'discount_value': o.discount_value, 'combo_price': o.combo_price, 'image_url': o.image_url,
            'is_active': o.is_active, 'valid_from': o.valid_from, 'valid_until': o.valid_until,
            'item_ids': [oi.menu_item_id for oi in o.items], 'items': names}


def _offer_is_current(o):
    if not o.is_active:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if o.valid_from and today < o.valid_from:
        return False
    if o.valid_until and today > o.valid_until:
        return False
    return True


@app.route('/api/offers')
def api_offers():
    return jsonify([_offer_dict(o) for o in Offer.query.all() if _offer_is_current(o)])


@app.route('/api/admin/offers', methods=['GET'])
@admin_required
def admin_list_offers():
    return jsonify([_offer_dict(o) for o in Offer.query.order_by(Offer.id.desc()).all()])


@app.route('/api/admin/offers', methods=['POST'])
@admin_required
def admin_create_offer():
    d = request.get_json(silent=True) or {}
    if not d.get('title'):
        return jsonify({'success': False, 'message': 'title required'}), 400
    o = Offer(title=d['title'], description=d.get('description', ''), offer_type=d.get('offer_type', 'percent'),
              discount_value=float(d.get('discount_value', 0) or 0), combo_price=float(d.get('combo_price', 0) or 0),
              image_url=d.get('image_url', ''), is_active=bool(d.get('is_active', True)),
              valid_from=d.get('valid_from') or None, valid_until=d.get('valid_until') or None)
    db.session.add(o)
    db.session.flush()
    for item_id in (d.get('item_ids') or []):
        if MenuItem.query.get(item_id):
            db.session.add(OfferItem(offer_id=o.id, menu_item_id=item_id))
    db.session.commit()
    return jsonify({'success': True, 'id': o.id}), 201


@app.route('/api/admin/offers/<int:oid>', methods=['PUT', 'PATCH'])
@admin_required
def admin_update_offer(oid):
    o = Offer.query.get(oid)
    if not o:
        return jsonify({'success': False, 'message': 'not found'}), 404
    d = request.get_json(silent=True) or {}
    for f in ['title', 'description', 'offer_type', 'image_url']:
        if f in d:
            setattr(o, f, d[f] or '')
    for f in ['valid_from', 'valid_until']:
        if f in d:
            setattr(o, f, d[f] or None)
    for f in ['discount_value', 'combo_price']:
        if f in d:
            try:
                setattr(o, f, float(d[f] or 0))
            except (TypeError, ValueError):
                pass
    if 'is_active' in d:
        o.is_active = bool(d['is_active'])
    if 'item_ids' in d:
        OfferItem.query.filter_by(offer_id=o.id).delete()
        for item_id in (d.get('item_ids') or []):
            if MenuItem.query.get(item_id):
                db.session.add(OfferItem(offer_id=o.id, menu_item_id=item_id))
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/offers/<int:oid>', methods=['DELETE'])
@admin_required
def admin_delete_offer(oid):
    o = Offer.query.get(oid)
    if o:
        db.session.delete(o)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# DATABASE INITIALIZATION & SEEDING
# ============================================================
def seed_menu():
    if Category.query.first() is not None:
        return

    default_imgs = {
        "Roasted Tomato Basil Soup": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=400&fit=crop",
        "Quinoa & Pomegranate Salad": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=400&fit=crop",
        "Truffle Mushroom Bruschetta": "https://images.unsplash.com/photo-1572695157366-5e585ab2b69f?w=400&fit=crop",
        "Edamame Hummus Platter": "https://images.unsplash.com/photo-1577805947697-89e18249d767?w=400&fit=crop",
        "Roasted Vegetable Risotto": "https://images.unsplash.com/photo-1476124369491-e7addf5db371?w=400&fit=crop",
        "Paneer Roulade": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=400&fit=crop",
        "Thai Green Curry Bowl": "https://images.unsplash.com/photo-1455619452474-d2be8b1e70cd?w=400&fit=crop",
        "Caprese Ciabatta": "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?w=400&fit=crop",
        "Smoked Gouda & Pear Melt": "https://images.unsplash.com/photo-1528736235302-52922df5c122?w=400&fit=crop",
        "Cold Brew Coffee": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=400&fit=crop",
        "Hibiscus Iced Tea": "https://images.unsplash.com/photo-1556679343-c7306c1976bc?w=400&fit=crop",
        "Turmeric Oat Latte": "https://images.unsplash.com/photo-1578899544867-3df4946b9e27?w=400&fit=crop",
        "Dark Chocolate Ganache Tart": "https://images.unsplash.com/photo-1551024506-0bccd828d307?w=400&fit=crop",
        "Saffron Infused Panna Cotta": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=400&fit=crop",
    }
    menu_data = {
        "Soups & Salads": [
            ("Roasted Tomato Basil Soup", 320, "Slow-roasted vine tomatoes, fresh basil, garlic croutons."),
            ("Quinoa & Pomegranate Salad", 480, "Organic quinoa, arugula, pomegranate seeds, toasted walnuts."),
        ],
        "Starters": [
            ("Truffle Mushroom Bruschetta", 450, "Wild mushrooms, truffle oil, balsamic glaze on sourdough."),
            ("Edamame Hummus Platter", 490, "Creamy edamame puree, crudités, warm za'atar flatbread."),
        ],
        "Main Course": [
            ("Roasted Vegetable Risotto", 750, "Arborio rice, seasonal roasted vegetables, parmesan crisp."),
            ("Paneer Roulade", 680, "Paneer stuffed with spinach and nuts, served with saffron gravy."),
            ("Thai Green Curry Bowl", 720, "Fragrant coconut-based curry, bamboo shoots, tofu, jasmine rice."),
        ],
        "Gourmet Sandwiches": [
            ("Caprese Ciabatta", 550, "Fresh mozzarella, heirloom tomatoes, basil pesto, arugula."),
            ("Smoked Gouda & Pear Melt", 580, "Caramelized pears, smoked gouda, arugula, honey drizzle on rye."),
        ],
        "Beverages": [
            ("Cold Brew Coffee", 250, "Slow-steeped 12-hour extraction."),
            ("Hibiscus Iced Tea", 220, "Floral, tart, and refreshing."),
            ("Turmeric Oat Latte", 280, "Golden milk with ginger, cinnamon, and creamy oat milk."),
        ],
        "Desserts": [
            ("Dark Chocolate Ganache Tart", 350, "70% cocoa, sea salt, raspberry coulis."),
            ("Saffron Infused Panna Cotta", 380, "Velvety Italian cream, saffron thread, pistachio crumble."),
        ],
    }
    fallback = "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400&fit=crop"
    for cat_name, items in menu_data.items():
        cat = Category(name=cat_name)
        db.session.add(cat)
        db.session.flush()
        for item_name, price, desc in items:
            db.session.add(MenuItem(name=item_name, price=price, description=desc,
                                    image_url=default_imgs.get(item_name, fallback), category_id=cat.id))
    db.session.commit()


def seed_admin():
    if User.query.filter_by(role='Admin').first():
        return
    admin_password = os.environ.get('ADMIN_PASSWORD')
    if not admin_password:
        if IS_PRODUCTION:
            print("[WARN] ADMIN_PASSWORD not set in production; skipping admin seed.")
            return
        admin_password = 'admin123'  # local-dev convenience only
        print("[WARN] ADMIN_PASSWORD not set; using dev default 'admin123' (do not use in production).")
    admin = User(username='admin', email=os.environ.get('ADMIN_EMAIL', 'admin@studio01.com'),
                 password=generate_password_hash(admin_password), role='Admin')
    db.session.add(admin)
    db.session.flush()
    db.session.add(ReferralCode(code='ADMIN01', owner_id=admin.id))
    db.session.commit()


def seed_tables():
    if Table.query.first() is not None:
        return
    layout = [
        ('T1', 2, 'indoor'), ('T2', 2, 'indoor'), ('T3', 2, 'indoor'), ('T4', 2, 'indoor'),
        ('T5', 4, 'indoor'), ('T6', 4, 'indoor'),
        ('P1', 4, 'terrace'), ('P2', 6, 'terrace'),
        ('G1', 4, 'outdoor'), ('G2', 6, 'outdoor'),
    ]
    for num, cap, loc in layout:
        db.session.add(Table(table_number=num, capacity=cap, location=loc, is_available=True))
    db.session.commit()


def seed_badges():
    if Badge.query.first() is not None:
        return
    badges = [
        ('first_order', 'First Order', 'Placed your very first order', 'lucide:sparkles', 'order_count', 1),
        ('coffee_lover', 'Coffee Lover', 'Completed 10 orders', 'lucide:coffee', 'order_count', 10),
        ('big_spender', 'Big Spender', 'Spent Rs.5000 in total', 'lucide:gem', 'total_spend', 5000),
        ('week_warrior', 'Week Warrior', '7-day ordering streak', 'lucide:flame', 'streak', 7),
        ('early_bird', 'Early Bird', 'Ordered before 9 AM', 'lucide:sunrise', 'early_bird', 1),
        ('review_master', 'Review Master', 'Wrote 5 reviews', 'lucide:star', 'review_count', 5),
    ]
    for key, name, desc, icon, rt, rv in badges:
        db.session.add(Badge(key=key, name=name, description=desc, icon=icon,
                             requirement_type=rt, requirement_value=rv))
    db.session.commit()


def seed_events():
    if Event.query.first() is not None:
        return
    events = [
        ('Coffee Brewing Workshop', 'Master pour-over, French press, and cold brew with our head barista.',
         '2026-01-15', '11:00', 90, 12, 799, 'https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600&fit=crop'),
        ('Latte Art Masterclass', 'Learn to pour hearts, rosettas, and tulips like a pro.',
         '2026-01-22', '16:00', 60, 10, 599, 'https://images.unsplash.com/photo-1541167760496-1628856ab772?w=600&fit=crop'),
        ('Vegan Baking Day', 'Hands-on session baking plant-based pastries and desserts.',
         '2026-02-05', '10:00', 120, 8, 999, 'https://images.unsplash.com/photo-1509440159596-0249088772ff?w=600&fit=crop'),
    ]
    for title, desc, date, time, dur, cap, price, img in events:
        db.session.add(Event(title=title, description=desc, date=date, time=time, duration_minutes=dur,
                             capacity=cap, price=price, image_url=img, is_active=True))
    db.session.commit()


def normalize_referral_codes():
    """Make each customer's referral code match their username (fixes older uppercased codes)."""
    changed = False
    for u in User.query.filter(User.role != 'Admin').all():
        ref = ReferralCode.query.filter_by(owner_id=u.id).first()
        desired = u.username[:10]
        if ref and ref.code != desired:
            clash = ReferralCode.query.filter(db.func.lower(ReferralCode.code) == desired.lower(),
                                              ReferralCode.owner_id != u.id).first()
            if not clash:
                ref.code = desired
                changed = True
    if changed:
        db.session.commit()


def init_db():
    with app.app_context():
        db.create_all()
        seed_menu()
        seed_tables()
        seed_badges()
        seed_events()
        seed_admin()
        normalize_referral_codes()


# Auto-init on import when explicitly enabled (set AUTO_INIT_DB=1 on Render).
if os.environ.get('AUTO_INIT_DB', '0') == '1':
    try:
        init_db()
    except Exception as _e:
        print(f"[WARN] init_db failed on import: {_e}")


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=not IS_PRODUCTION)
