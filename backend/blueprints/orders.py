"""Orders blueprint: public menu browsing, customer profile/orders, payment
initiation + verification, order creation, and table reservations.
"""
import json
from urllib.parse import quote
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from models import db, Category, MenuItem, Special, Review, User, Order, Reservation, Table
from helpers import (current_user_id, get_redeemable_items, calculate_coins, update_streak,
                     evaluate_and_award_badges, badges_payload, user_public, send_order_email,
                     verify_razorpay_signature, _conflicting_table_ids)
from services import razorpay_client, razorpay_init_error, maybe_capture_exception

orders_bp = Blueprint('orders', __name__)


# ============================================================
# PUBLIC MENU ROUTES
# ============================================================
@orders_bp.route('/api/menu')
def api_menu():
    categories = Category.query.options(joinedload(Category.items)).all()
    # Preferred display order — Starters first, Beverages last.
    _CAT_ORDER = ["Starters", "Soups & Salads", "Gourmet Sandwiches", "Main Course", "Desserts", "Beverages"]
    def _sort_key(cat):
        try:
            return _CAT_ORDER.index(cat.name)
        except ValueError:
            return len(_CAT_ORDER)  # unknown categories go to the end
    categories.sort(key=_sort_key)

    menu_dict = {}
    for cat in categories:
        menu_dict[cat.name] = {
            item.name: {
                "price": item.price, "description": item.description,
                "image_url": item.image_url, "sold_out": item.is_sold_out,
            } for item in cat.items
        }
    customizations = {
        "Starters": [
            {"name": "Extra Mint Chutney", "price": 30},
            {"name": "Garlic Mayo Dip", "price": 40},
            {"name": "Liquid Cheese Sauce", "price": 50},
        ],
        "Soups & Salads": [
            {"name": "Herb Garlic Bread Toast", "price": 60},
            {"name": "Extra Feta Cheese", "price": 50},
            {"name": "Multigrain Croutons", "price": 40},
        ],
        "Gourmet Sandwiches": [
            {"name": "Salted French Fries", "price": 80},
            {"name": "Peri-Peri Potato Wedges", "price": 90},
            {"name": "Extra Cheese Slice", "price": 40},
        ],
        "Main Course": [
            {"name": "Butter Garlic Naan", "price": 60},
            {"name": "Cucumber Mint Raita", "price": 40},
            {"name": "Roasted Masala Papad", "price": 30},
        ],
        "Desserts": [
            {"name": "Scoop of Vanilla Bean Ice Cream", "price": 80},
            {"name": "Extra Hot Fudge Sauce", "price": 40},
            {"name": "Crushed Mixed Nuts", "price": 30},
        ],
        "Beverages": [
            {"name": "Extra Espresso Shot", "price": 50},
            {"name": "Boba Pearls", "price": 60},
            {"name": "Vanilla/Hazelnut Syrup Pump", "price": 40},
        ],
    }
    return jsonify({"menu": menu_dict, "customizations": customizations})


@orders_bp.route('/api/redeemable-items')
def api_redeemable():
    return jsonify(get_redeemable_items())


@orders_bp.route('/api/special')
def api_special():
    s = Special.query.filter_by(active=True).first()
    if not s:
        return jsonify({"active": False})
    return jsonify({"active": True, "item": s.item, "discount": s.discount})


@orders_bp.route('/api/soldout')
def api_soldout():
    items = MenuItem.query.filter_by(is_sold_out=True).with_entities(MenuItem.name).all()
    return jsonify([i[0] for i in items])


@orders_bp.route('/api/reviews')
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
@orders_bp.route('/api/user/profile')
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


@orders_bp.route('/api/user/orders')
@jwt_required()
def api_user_orders():
    orders = Order.query.filter_by(user_id=current_user_id()).order_by(Order.id.desc()).all()
    return jsonify([{
        "id": o.id, "order_id": o.order_id, "items": json.loads(o.items), "total": o.total,
        "coins_used": o.coins_used, "currency_paid": o.currency_paid, "date_time": o.date_time,
        "status": o.status,
    } for o in orders])


@orders_bp.route('/api/user/orders/<int:oid>/review', methods=['POST'])
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


def _block_admins():
    """Customer checkout is for customers only. Staff use the dashboard POS."""
    if get_jwt().get('role') == 'Admin':
        return jsonify({'success': False,
                        'message': 'Staff accounts take orders from the dashboard POS, not the customer checkout.'}), 403
    return None


@orders_bp.route('/api/create-razorpay-order', methods=['POST'])
@jwt_required()
def create_razorpay_order():
    blocked = _block_admins()
    if blocked:
        return blocked
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


@orders_bp.route('/api/verify-payment', methods=['POST'])
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


@orders_bp.route('/api/order', methods=['POST'])
@jwt_required()
def api_order():
    blocked = _block_admins()
    if blocked:
        return blocked
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


@orders_bp.route('/api/book', methods=['POST'])
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
# TABLES (public availability)
# ============================================================
@orders_bp.route('/api/tables')
def api_tables():
    date = request.args.get('date')
    time = request.args.get('time')
    booked = _conflicting_table_ids(date, time) if date and time else set()
    tables = Table.query.order_by(Table.table_number).all()
    return jsonify([{'id': t.id, 'table_number': t.table_number, 'capacity': t.capacity,
                     'location': t.location,
                     'available': bool(t.is_available and t.id not in booked)} for t in tables])
