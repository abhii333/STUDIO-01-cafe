"""STUDIO 01 — SQLAlchemy models.

The single ``db`` instance lives here and is initialised against the app in
``app.py`` via ``db.init_app(app)``. Every model imports from this module.
"""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
    # Staff POS metadata (NULL for customer/online orders).
    channel = db.Column(db.String(20), nullable=True)        # 'online' | 'pos-dinein' | 'pos-takeaway'
    customer_label = db.Column(db.String(80), nullable=True)  # walk-in customer name (POS)
    table_label = db.Column(db.String(20), nullable=True)     # table number for dine-in (POS)
    # Razorpay dynamic UPI QR (POS scan-to-pay auto-confirmation).
    upi_qr_id = db.Column(db.String(64), nullable=True)       # Razorpay qr_... id
    upi_qr_url = db.Column(db.String(500), nullable=True)     # hosted QR image URL


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


class GroupOrder(db.Model):
    """A shared cart that several people contribute to before it's placed as one order."""
    id = db.Column(db.Integer, primary_key=True)
    join_code = db.Column(db.String(12), unique=True, nullable=False)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(120), default='Group Order')
    status = db.Column(db.String(20), default='open')  # open | locked | placed | cancelled
    order_id = db.Column(db.Integer, nullable=True)    # set once finalized into an Order
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    contributions = db.relationship('GroupOrderContribution', backref='group', lazy=True,
                                    cascade='all, delete-orphan')


class GroupOrderContribution(db.Model):
    """One participant's items within a group order."""
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group_order.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    participant_name = db.Column(db.String(80), nullable=False)
    items = db.Column(db.Text, nullable=False, default='[]')  # JSON list of {name, price, quantity}
    subtotal = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('group_id', 'user_id', name='uq_group_user'),)
