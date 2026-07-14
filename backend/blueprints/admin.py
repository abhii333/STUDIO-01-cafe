"""Admin blueprint: order management, stats, audits, menu/category CRUD,
tables, events, offers, photos, and image upload. All routes require Admin.
"""
import os
import json
from collections import Counter
from urllib.parse import quote
from datetime import datetime

from flask import Blueprint, request, jsonify

from models import (db, Order, User, Reservation, OrderAudit, Special, MenuItem,
                    Category, Table, Photo, Event, EventRegistration, Offer, OfferItem)
from helpers import admin_required, current_user_id, send_order_email, _offer_dict, _event_dict
from services import cloudinary, maybe_capture_exception, razorpay_client

admin_bp = Blueprint('admin', __name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


# ============================================================
# ORDERS / RESERVATIONS / STATS / AUDITS
# ============================================================
@admin_bp.route('/api/admin/orders')
@admin_required
def api_admin_orders():
    orders = Order.query.order_by(Order.id.desc()).all()
    out = []
    for o in orders:
        name = None
        if o.user_id:
            u = User.query.get(o.user_id)
            name = u.username if u else None
        # POS/walk-in orders have no account — fall back to the label staff typed.
        name = name or o.customer_label or "Walk-in"
        out.append({
            "order_id": o.order_id, "customer_name": name,
            "items": json.loads(o.items), "total": o.total, "currency_paid": o.currency_paid,
            "date_time": o.date_time, "status": o.status, "payment_id": o.payment_id,
            "payment_method": o.payment_method,
            "channel": o.channel, "table": o.table_label,
        })
    return jsonify(out)


@admin_bp.route('/api/admin/pos-order', methods=['POST'])
@admin_required
def pos_order():
    """Staff Point-of-Sale: create a walk-in / dine-in / takeaway order for a guest.

    Deliberately separate from the customer /api/order flow — no loyalty coins,
    no customer account, no signature checks. This is how staff ring up orders.
    """
    d = request.get_json(silent=True) or {}
    items, total = [], 0.0
    for it in (d.get('items') or []):
        if not isinstance(it, dict):
            continue
        name = str(it.get('name', '')).strip()[:120]
        try:
            price = float(it.get('price', 0) or 0)
            qty = int(it.get('quantity', 1) or 1)
        except (TypeError, ValueError):
            continue
        if not name or qty <= 0 or price < 0:
            continue
        qty = min(qty, 99)
        items.append({'name': name, 'price': price, 'quantity': qty})
        total += price * qty
    if not items:
        return jsonify({'success': False, 'message': 'Add at least one item to the order.'}), 400

    order_type = (d.get('order_type') or 'dine-in').strip().lower()
    channel = 'pos-dinein' if order_type == 'dine-in' else 'pos-takeaway'
    table_label = (d.get('table_number') or '').strip()[:20] or None
    customer_label = (d.get('customer_name') or '').strip()[:80] or None

    # Table number and customer name are mandatory for all POS orders.
    if not customer_label:
        return jsonify({'success': False, 'message': 'Customer name is required.'}), 400
    if order_type == 'dine-in' and not table_label:
        return jsonify({'success': False, 'message': 'Table number is required for dine-in orders.'}), 400

    payment_method = (d.get('payment_method') or 'Cash').strip()[:100]
    mark_paid = bool(d.get('mark_paid', True))
    total = round(total, 2)

    # Compute GST breakdown (Indian law: prices are GST-inclusive).
    from helpers import compute_gst, generate_bill_image_url
    gst_info = compute_gst(total)

    # UPI + not-yet-collected + Razorpay configured => show a scan-to-pay QR that
    # auto-confirms via the webhook. Otherwise it's a manual (staff-confirmed) order.
    wants_online_upi = payment_method.strip().upper() == 'UPI' and not mark_paid and razorpay_client is not None

    max_id = db.session.query(db.func.max(Order.order_id)).scalar()
    new_oid = (max_id or 0) + 1
    time_now = datetime.now().strftime("%d-%m-%Y %I:%M %p")

    if wants_online_upi:
        status, payment_id = 'Pending', None
    elif mark_paid:
        status, payment_id = 'Paid', f"counter-{int(datetime.utcnow().timestamp())}"
    else:
        status, payment_id = 'Pending', None

    order = Order(
        order_id=new_oid, user_id=None, items=json.dumps(items), total=total,
        coins_used=0, currency_paid=total, date_time=time_now,
        status=status, payment_id=payment_id,
        payment_method=payment_method, channel=channel,
        customer_label=customer_label, table_label=table_label,
    )
    db.session.add(order)
    try:
        db.session.add(OrderAudit(
            order_id=new_oid, admin_id=current_user_id(), action='pos_order',
            meta=json.dumps({'channel': channel, 'table': table_label,
                             'customer': customer_label, 'payment': payment_method, 'paid': status == 'Paid'})))
    except Exception as exc:
        maybe_capture_exception(exc)
    db.session.commit()

    # Generate bill image URL for sharing / printing.
    bill_image_url, bill_text = generate_bill_image_url(
        new_oid, items, gst_info, time_now,
        customer_name=customer_label, table=table_label, payment_method=payment_method)

    resp = {'success': True, 'order_id': new_oid, 'total': total, 'status': order.status,
            'gst': gst_info, 'bill_image_url': bill_image_url, 'bill_text': bill_text,
            'customer_name': customer_label, 'table': table_label}

    # Generate a Razorpay dynamic UPI QR for the exact amount (works in test mode
    # with test keys; swap to live keys at go-live — no code change needed).
    if wants_online_upi:
        try:
            qr = razorpay_client.qrcode.create({
                'type': 'upi_qr',
                'name': 'STUDIO 01',
                'usage': 'single_use',
                'fixed_amount': True,
                'payment_amount': int(round(total * 100)),
                'description': f'Order #{new_oid}',
                'notes': {'order_ref': str(new_oid)},
            })
            order.upi_qr_id = qr.get('id')
            order.upi_qr_url = qr.get('image_url')
            db.session.commit()
            resp['upi_qr'] = {'id': qr.get('id'), 'image_url': qr.get('image_url'), 'amount': total}
        except Exception as exc:
            maybe_capture_exception(exc)
            resp['upi_qr_error'] = 'Could not create the payment QR — collect manually and mark paid.'

    return jsonify(resp)


@admin_bp.route('/api/admin/orders/<int:oid>/status')
@admin_required
def order_status(oid):
    """Lightweight status poll for the POS QR screen."""
    o = Order.query.filter_by(order_id=oid).first()
    if not o:
        return jsonify({'success': False, 'message': 'not found'}), 404
    return jsonify({'success': True, 'order_id': o.order_id, 'status': o.status,
                    'paid': o.status == 'Paid', 'payment_id': o.payment_id})


@admin_bp.route('/api/admin/update-order-status', methods=['POST'])
@admin_required
def update_status():
    data = request.get_json(silent=True) or {}
    o = Order.query.filter_by(order_id=data.get('order_id')).first()
    if o:
        o.status = data.get('status')
        db.session.commit()
    return jsonify({"success": True})


@admin_bp.route('/api/admin/mark-paid', methods=['POST'])
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


@admin_bp.route('/api/admin/reservations')
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


@admin_bp.route('/api/admin/stats')
@admin_required
def admin_stats():
    orders = Order.query.filter_by(status='Completed').all()
    revenue = {}
    for o in orders:
        day = o.date_time.split()[0]
        revenue[day] = revenue.get(day, 0) + o.currency_paid
    return jsonify(revenue)


@admin_bp.route('/api/admin/audits')
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


@admin_bp.route('/api/admin/special', methods=['POST'])
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


@admin_bp.route('/api/admin/toggle-soldout', methods=['POST'])
@admin_required
def toggle_soldout():
    data = request.get_json(silent=True) or {}
    item = MenuItem.query.filter_by(name=data.get('item')).first()
    if item:
        item.is_sold_out = not item.is_sold_out
        db.session.commit()
    return jsonify({"success": True})


@admin_bp.route('/api/admin/upload-image', methods=['POST'])
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
# MENU MANAGEMENT (categories + items)
# ============================================================
def _menu_item_dict(item):
    return {
        'id': item.id, 'name': item.name, 'price': item.price,
        'description': item.description, 'image_url': item.image_url,
        'category_id': item.category_id,
        'category': item.category.name if item.category else None,
        'is_sold_out': item.is_sold_out,
    }


@admin_bp.route('/api/admin/categories', methods=['GET'])
@admin_required
def admin_list_categories():
    return jsonify([{'id': c.id, 'name': c.name} for c in Category.query.order_by(Category.name).all()])


@admin_bp.route('/api/admin/categories', methods=['POST'])
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


@admin_bp.route('/api/admin/menu-items', methods=['GET'])
@admin_required
def admin_list_menu_items():
    items = MenuItem.query.order_by(MenuItem.category_id, MenuItem.name).all()
    return jsonify([_menu_item_dict(i) for i in items])


@admin_bp.route('/api/admin/menu-items', methods=['POST'])
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


@admin_bp.route('/api/admin/menu-items/<int:item_id>', methods=['PUT', 'PATCH'])
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


@admin_bp.route('/api/admin/menu-items/<int:item_id>', methods=['DELETE'])
@admin_required
def admin_delete_menu_item(item_id):
    item = MenuItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'message': 'Item not found.'}), 404
    # Safe cleanup: deactivate the Special if it referenced this item.
    # (Historical orders/reviews reference item names as snapshots and are untouched.)
    Special.query.filter_by(item=item.name).update({Special.active: False})
    OfferItem.query.filter_by(menu_item_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# TABLES (admin management)
# ============================================================
@admin_bp.route('/api/admin/tables', methods=['GET'])
@admin_required
def admin_list_tables():
    return jsonify([{'id': t.id, 'table_number': t.table_number, 'capacity': t.capacity,
                     'location': t.location, 'is_available': t.is_available}
                    for t in Table.query.order_by(Table.table_number).all()])


@admin_bp.route('/api/admin/tables', methods=['POST'])
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


@admin_bp.route('/api/admin/tables/<int:tid>', methods=['PATCH'])
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


@admin_bp.route('/api/admin/tables/<int:tid>', methods=['DELETE'])
@admin_required
def admin_delete_table(tid):
    t = Table.query.get(tid)
    if t:
        db.session.delete(t)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# PHOTOS / GALLERY (admin management)
# ============================================================
@admin_bp.route('/api/admin/photos', methods=['POST'])
@admin_required
def admin_add_photo():
    d = request.get_json(silent=True) or {}
    if not d.get('image_url'):
        return jsonify({'success': False, 'message': 'image_url required'}), 400
    p = Photo(image_url=d['image_url'], caption=(d.get('caption') or '')[:200], user_id=current_user_id())
    db.session.add(p)
    db.session.commit()
    return jsonify({'success': True, 'id': p.id}), 201


@admin_bp.route('/api/admin/photos/<int:pid>', methods=['DELETE'])
@admin_required
def admin_delete_photo(pid):
    p = Photo.query.get(pid)
    if p:
        db.session.delete(p)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# EVENTS (admin management)
# ============================================================
@admin_bp.route('/api/admin/events', methods=['GET'])
@admin_required
def admin_list_events():
    return jsonify([_event_dict(e) for e in Event.query.order_by(Event.date).all()])


@admin_bp.route('/api/admin/events', methods=['POST'])
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


@admin_bp.route('/api/admin/events/<int:eid>', methods=['PUT', 'PATCH'])
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


@admin_bp.route('/api/admin/events/<int:eid>', methods=['DELETE'])
@admin_required
def admin_delete_event(eid):
    e = Event.query.get(eid)
    if e:
        EventRegistration.query.filter_by(event_id=eid).delete()
        db.session.delete(e)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# OFFERS / MEAL DEALS (admin management)
# ============================================================
@admin_bp.route('/api/admin/offers', methods=['GET'])
@admin_required
def admin_list_offers():
    return jsonify([_offer_dict(o) for o in Offer.query.order_by(Offer.id.desc()).all()])


@admin_bp.route('/api/admin/offers', methods=['POST'])
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


@admin_bp.route('/api/admin/offers/<int:oid>', methods=['PUT', 'PATCH'])
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


@admin_bp.route('/api/admin/offers/<int:oid>', methods=['DELETE'])
@admin_required
def admin_delete_offer(oid):
    o = Offer.query.get(oid)
    if o:
        db.session.delete(o)
        db.session.commit()
    return jsonify({'success': True})


# ============================================================
# ANALYTICS DASHBOARD (aggregated from existing tables)
# ============================================================
def _parse_order_dt(s):
    for fmt in ("%d-%m-%Y %I:%M %p", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


@admin_bp.route('/api/admin/analytics/dashboard')
@admin_required
def analytics_dashboard():
    """Business analytics computed on the fly from Orders (no new tables):
    revenue trend by day, top items, customer segments, and peak hours.
    """
    orders = Order.query.all()

    rev_by_day = {}          # 'YYYY-MM-DD' -> [revenue, order_count]
    item_qty = Counter()
    item_rev = Counter()
    hour_counts = Counter()
    orders_by_user = Counter()
    spend_by_user = Counter()
    total_revenue = 0.0
    total_items = 0
    guest_orders = 0

    for o in orders:
        paid = o.currency_paid or 0
        total_revenue += paid

        dt = _parse_order_dt(o.date_time or '')
        if dt:
            key = dt.strftime("%Y-%m-%d")
            bucket = rev_by_day.setdefault(key, [0.0, 0])
            bucket[0] += paid
            bucket[1] += 1
            hour_counts[dt.hour] += 1

        try:
            for it in json.loads(o.items):
                base = str(it.get('name', '')).split(' [')[0]
                qty = int(it.get('quantity', 1) or 1)
                item_qty[base] += qty
                item_rev[base] += (it.get('price', 0) or 0) * qty
                total_items += qty
        except Exception:
            pass

        if o.user_id:
            orders_by_user[o.user_id] += 1
            spend_by_user[o.user_id] += paid
        else:
            guest_orders += 1

    # Revenue trend (chronological, most recent 30 days that have orders).
    revenue_trend = [{'date': k, 'revenue': round(v[0], 2), 'orders': v[1]}
                     for k, v in sorted(rev_by_day.items())][-30:]

    # Top items by quantity sold.
    top_items = [{'name': name, 'quantity': int(qty), 'revenue': round(item_rev[name], 2)}
                 for name, qty in item_qty.most_common(10)]

    # Peak hours: order volume per hour of day (0-23).
    peak_hours = [{'hour': h, 'orders': hour_counts.get(h, 0)} for h in range(24)]
    peak_hour = max(range(24), key=lambda h: hour_counts.get(h, 0)) if hour_counts else None

    # Customer segments by number of orders placed.
    new_c = returning_c = vip_c = 0
    for _uid, cnt in orders_by_user.items():
        if cnt >= 5:
            vip_c += 1
        elif cnt >= 2:
            returning_c += 1
        else:
            new_c += 1

    total_orders = len(orders)
    unique_customers = len(orders_by_user)
    aov = round(total_revenue / total_orders, 2) if total_orders else 0

    return jsonify({
        'summary': {
            'total_revenue': round(total_revenue, 2),
            'total_orders': total_orders,
            'avg_order_value': aov,
            'unique_customers': unique_customers,
            'items_sold': int(total_items),
            'guest_orders': guest_orders,
        },
        'revenue_trend': revenue_trend,
        'top_items': top_items,
        'customer_segments': {
            'new': new_c,
            'returning': returning_c,
            'vip': vip_c,
            'guest_orders': guest_orders,
        },
        'peak_hours': peak_hours,
        'peak_hour': peak_hour,
    })
