"""Shared helpers used across blueprints: auth utilities, domain logic,
gamification, reservation conflict checks, payment signature, and serializers.
"""
import os
import json
import hmac
import hashlib
import random
from functools import wraps
from datetime import datetime, timedelta

from flask import jsonify
from flask_jwt_extended import (
    jwt_required, get_jwt, get_jwt_identity,
    create_access_token, create_refresh_token,
)
from werkzeug.security import generate_password_hash

from models import (db, User, Order, Review, ReferralCode, Category, MenuItem,
                    Reservation, Badge, UserBadge)
from services import maybe_capture_exception


# ============================================================
# AUTH HELPERS
# ============================================================
# Full 600k-iteration pbkdf2 is very slow on a 0.1-vCPU free tier. 150k is still
# strong for a demo and cuts login/registration time dramatically.
PWD_METHOD = 'pbkdf2:sha256:150000'


def hash_password(pw):
    return generate_password_hash(pw, method=PWD_METHOD)


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
    redeemable_cats = ['Hot Coffee', 'Cold Coffee', 'Beverages', 'Sides & Snacks', 'Desserts']
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
        from circuit_breaker import smtp_breaker
        def _send():
            with smtplib.SMTP(mail_host, mail_port, timeout=10) as s:
                s.starttls()
                if mail_user and mail_pass:
                    s.login(mail_user, mail_pass)
                s.send_message(msg)
        smtp_breaker.call(_send)
    except Exception as e:
        maybe_capture_exception(e)


# ============================================================
# PAYMENTS
# ============================================================
def verify_razorpay_signature(order_id, payment_id, signature):
    """Razorpay Standard Checkout signature check: HMAC-SHA256(order_id|payment_id, KEY_SECRET)."""
    secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
    if not (secret and order_id and payment_id and signature):
        return False
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


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
    """Compute badge-relevant stats using efficient queries (no N+1)."""
    from sqlalchemy import func
    order_count = Order.query.filter_by(user_id=user.id).count()
    total_spend = db.session.query(func.coalesce(func.sum(Order.currency_paid), 0)).filter(
        Order.user_id == user.id).scalar()
    review_count = Review.query.filter_by(user_id=user.id).count()
    # Early bird: check if any order was before 9 AM (parse stored date_time strings).
    early = False
    early_orders = Order.query.filter_by(user_id=user.id).with_entities(Order.date_time).all()
    for (dt_str,) in early_orders:
        try:
            if datetime.strptime(dt_str, "%d-%m-%Y %I:%M %p").hour < 9:
                early = True
                break
        except Exception:
            pass
    return {
        'order_count': order_count,
        'total_spend': float(total_spend),
        'review_count': review_count,
        'streak': user.current_streak or 0,
        'early_bird': early,
    }


def evaluate_and_award_badges(user):
    stats = _user_stats(user)
    earned_ids = {ub.badge_id for ub in UserBadge.query.filter_by(user_id=user.id).all()}
    newly = []
    new_badge_objs = []
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
            new_badge_objs.append(UserBadge(user_id=user.id, badge_id=badge.id))
            newly.append({'key': badge.key, 'name': badge.name, 'icon': badge.icon,
                          'description': badge.description})
    if new_badge_objs:
        db.session.add_all(new_badge_objs)
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
# RESERVATIONS — TABLE CONFLICT CHECKS
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


# ============================================================
# SERIALIZERS (shared between admin + public blueprints)
# ============================================================
def _event_dict(e):
    return {'id': e.id, 'title': e.title, 'description': e.description, 'date': e.date, 'time': e.time,
            'duration_minutes': e.duration_minutes, 'capacity': e.capacity,
            'registered_count': e.registered_count, 'price': e.price, 'image_url': e.image_url,
            'is_active': e.is_active, 'is_sold_out': e.registered_count >= e.capacity}


def _offer_dict(o):
    # Batch-load item names instead of individual query per OfferItem (fixes N+1).
    item_ids = [oi.menu_item_id for oi in o.items]
    names = []
    if item_ids:
        items = MenuItem.query.filter(MenuItem.id.in_(item_ids)).all()
        name_map = {mi.id: mi.name for mi in items}
        names = [name_map[mid] for mid in item_ids if mid in name_map]
    return {'id': o.id, 'title': o.title, 'description': o.description, 'offer_type': o.offer_type,
            'discount_value': o.discount_value, 'combo_price': o.combo_price, 'image_url': o.image_url,
            'is_active': o.is_active, 'valid_from': o.valid_from, 'valid_until': o.valid_until,
            'item_ids': item_ids, 'items': names}


def _offer_is_current(o):
    if not o.is_active:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if o.valid_from and today < o.valid_from:
        return False
    if o.valid_until and today > o.valid_until:
        return False
    return True


# ============================================================
# GST-COMPLIANT BILL (Indian law) + Bill image URL generation
# ============================================================
# Default 5% GST (2.5% CGST + 2.5% SGST) for non-AC restaurants.
# Set GST_RATE env to "18" for AC restaurants / bars.
GST_RATE = float(os.environ.get('GST_RATE', '5'))
CAFE_NAME = os.environ.get('CAFE_NAME', 'STUDIO 01')
CAFE_GSTIN = os.environ.get('CAFE_GSTIN', '')  # set once GST-registered


def compute_gst(subtotal):
    """Compute GST breakdown from a subtotal (items total before tax).
    Returns dict with base, cgst, sgst, gst_total, grand_total, gst_rate.
    Indian cafes include GST in the menu price (MRP = inclusive), so we
    reverse-calculate: base = subtotal / (1 + rate/100), tax = subtotal - base.
    """
    rate = GST_RATE
    base = round(subtotal / (1 + rate / 100), 2)
    gst_total = round(subtotal - base, 2)
    cgst = round(gst_total / 2, 2)
    sgst = gst_total - cgst  # avoid rounding drift
    return {
        'subtotal': round(subtotal, 2),
        'base_amount': base,
        'cgst_rate': round(rate / 2, 2),
        'sgst_rate': round(rate / 2, 2),
        'cgst': cgst,
        'sgst': round(sgst, 2),
        'gst_total': gst_total,
        'grand_total': round(subtotal, 2),
        'gst_rate': rate,
    }


def generate_bill_image_url(order_id, items, gst_info, date_time, customer_name=None, table=None, payment_method=None):
    """Generate a hosted bill image URL using QuickChart (free).
    Returns a URL to a PNG image of the bill that can be shared/printed.
    """
    from urllib.parse import quote as url_quote

    lines = []
    lines.append(CAFE_NAME)
    if CAFE_GSTIN:
        lines.append(f'GSTIN: {CAFE_GSTIN}')
    lines.append('=' * 32)
    lines.append(f'Bill No: #{order_id}')
    lines.append(f'Date: {date_time}')
    if customer_name:
        lines.append(f'Customer: {customer_name}')
    if table:
        lines.append(f'Table: {table}')
    lines.append('-' * 32)
    lines.append(f'{"Item":<18}{"Qty":>3} {"Amt":>8}')
    lines.append('-' * 32)
    for it in items:
        name = str(it.get('name', ''))[:18]
        qty = it.get('quantity', 1)
        amt = round(it.get('price', 0) * qty, 2)
        lines.append(f'{name:<18}{qty:>3} {amt:>8.2f}')
    lines.append('-' * 32)
    lines.append(f'{"Subtotal":<22} {gst_info["subtotal"]:>8.2f}')
    lines.append(f'{"Base Amount":<22} {gst_info["base_amount"]:>8.2f}')
    lines.append(f'{"CGST @" + str(gst_info["cgst_rate"]) + "%":<22} {gst_info["cgst"]:>8.2f}')
    lines.append(f'{"SGST @" + str(gst_info["sgst_rate"]) + "%":<22} {gst_info["sgst"]:>8.2f}')
    lines.append('=' * 32)
    lines.append(f'{"TOTAL":<22} {gst_info["grand_total"]:>8.2f}')
    lines.append('=' * 32)
    if payment_method:
        lines.append(f'Payment: {payment_method}')
    lines.append('')
    lines.append('Thank you for visiting!')
    lines.append('Go green - paperless billing')

    bill_text = '\n'.join(lines)
    # QuickChart text-to-image (free, no signup needed)
    encoded = url_quote(bill_text)
    # Use QuickChart's QR endpoint as a simple text-to-image isn't available,
    # so we use the QR code of the bill text as the "bill image" (scannable receipt).
    bill_image_url = f'https://quickchart.io/qr?text={encoded}&size=400&margin=2&dark=1C1410&light=FAF7F2'
    return bill_image_url, bill_text
