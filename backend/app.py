"""STUDIO 01 — Backend API (application wiring).

This module is intentionally thin: it builds the Flask app, initialises the
shared extensions, registers the feature blueprints, and owns a couple of
infra routes (health/config) plus error handling and DB seeding.

Layout:
  models.py            SQLAlchemy db + all models
  extensions.py        jwt, limiter (unbound, init_app'd here)
  services.py          optional integrations (razorpay/cloudinary/sentry) + flags
  helpers.py           shared auth/domain/gamification helpers + serializers
  seed.py              idempotent seeding + data normalization
  blueprints/          auth, orders, admin, social
"""
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify
from flask_cors import CORS

# Re-export models (tests import e.g. `from app import Category`) and db.
from models import (db, User, Order, Reservation, Review, ReferralCode, Special,  # noqa: F401
                    OrderAudit, Category, MenuItem, Table, Badge, UserBadge, Photo,
                    Event, EventRegistration, Offer, OfferItem,
                    GroupOrder, GroupOrderContribution)
from extensions import jwt, limiter
from services import IS_PRODUCTION
# Re-export seeding (tests/conftest import these from `app`).
from seed import (seed_menu, seed_admin, seed_tables, seed_badges, seed_events,  # noqa: F401
                  normalize_referral_codes, fix_broken_menu_images, ensure_schema)
from blueprints.auth import auth_bp
from blueprints.orders import orders_bp
from blueprints.admin import admin_bp
from blueprints.social import social_bp
from blueprints.group import group_bp


# ============================================================
# CONFIG
# ============================================================
def _normalize_db_url(url):
    """Render/Heroku hand out postgres:// URLs; SQLAlchemy needs postgresql://."""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = _normalize_db_url(os.environ.get('DATABASE_URL')) or 'sqlite:///cafe.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Preserve dict key insertion order in JSON responses (menu category ordering matters).
app.config['JSON_SORT_KEYS'] = False
app.json.sort_keys = False
# Reuse DB connections and drop stale ones (matters for a remote Postgres like Neon).
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 280}

# JWT
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET') or os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)

# Rate limiting (in-memory; free-tier friendly). Toggle off in tests via RATELIMIT_ENABLED=0.
app.config['RATELIMIT_ENABLED'] = os.environ.get('RATELIMIT_ENABLED', '1') != '0'
app.config['RATELIMIT_HEADERS_ENABLED'] = True

# Wire up shared extensions.
db.init_app(app)
jwt.init_app(app)
limiter.init_app(app)

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

# Register feature blueprints.
app.register_blueprint(auth_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(social_bp)
app.register_blueprint(group_bp)


# ============================================================
# ERROR HANDLERS & SECURITY HEADERS
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(429)
def ratelimit_exceeded(e):
    # Clear, JSON-shaped response the frontend surfaces as a toast.
    return jsonify({
        "success": False,
        "error": "rate_limited",
        "message": "Too many attempts. Please wait a minute and try again.",
    }), 429


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
# DATABASE INITIALIZATION
# ============================================================
def init_db():
    with app.app_context():
        db.create_all()
        ensure_schema()  # add any columns missing on an already-seeded DB
        seed_menu()
        seed_tables()
        seed_badges()
        seed_events()
        seed_admin()
        normalize_referral_codes()
        fix_broken_menu_images()


# Auto-init on import when explicitly enabled (set AUTO_INIT_DB=1 on Render).
if os.environ.get('AUTO_INIT_DB', '0') == '1':
    try:
        init_db()
    except Exception as _e:
        print(f"[WARN] init_db failed on import: {_e}")


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=not IS_PRODUCTION)
