"""Group orders: a host opens a shared order, others join with a code, everyone
adds their own items, and the bill can be split itemized or evenly.
"""
import json
import secrets
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from models import db, GroupOrder, GroupOrderContribution, User, Order
from helpers import current_user_id
from blueprints.orders import _recompute_item_unit_price

group_bp = Blueprint('group', __name__)

# Unambiguous alphabet (no O/0, I/1, etc.) for human-shareable codes.
_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


def _gen_join_code(length=6):
    for _ in range(12):
        code = ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
        if not GroupOrder.query.filter_by(join_code=code).first():
            return code
    return ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(length + 4))


def _clean_items(raw):
    """Validate/normalize an incoming items list and compute its subtotal.

    SECURITY: prices are recomputed from the menu (same as customer checkout
    and POS) — a participant's submitted price is never trusted directly.
    Returns (items, subtotal, error_msg). error_msg is None if all items valid.
    """
    items, subtotal = [], 0.0
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        name = str(it.get('name', '')).strip()[:120]
        try:
            qty = int(it.get('quantity', 1) or 1)
        except (TypeError, ValueError):
            continue
        if not name or qty <= 0:
            continue
        qty = min(qty, 99)
        _, unit_price = _recompute_item_unit_price(name)
        if unit_price is None:
            return [], 0, f'Unknown item: {name}. Please remove it and try again.'
        items.append({'name': name, 'price': round(unit_price, 2), 'quantity': qty})
        subtotal += unit_price * qty
    return items, round(subtotal, 2), None


def _group_state(group, viewer_id):
    participants, itemized, grand = [], [], 0.0
    for c in sorted(group.contributions, key=lambda c: c.id):
        try:
            items = json.loads(c.items)
        except Exception:
            items = []
        participants.append({
            'user_id': c.user_id,
            'name': c.participant_name,
            'items': items,
            'subtotal': round(c.subtotal, 2),
            'is_you': viewer_id is not None and c.user_id == viewer_id,
        })
        itemized.append({'name': c.participant_name, 'amount': round(c.subtotal, 2)})
        grand += c.subtotal
    grand = round(grand, 2)
    n = len(participants)
    host = User.query.get(group.host_id)
    return {
        'join_code': group.join_code,
        'title': group.title,
        'status': group.status,
        'host_id': group.host_id,
        'host_name': host.username if host else 'Host',
        'is_host': viewer_id is not None and viewer_id == group.host_id,
        'order_id': group.order_id,
        'participants': participants,
        'grand_total': grand,
        'split': {
            'itemized': itemized,
            'equal': {'people': n, 'per_person': round(grand / n, 2) if n else 0},
        },
    }


def _get_group_or_404(code):
    return GroupOrder.query.filter_by(join_code=(code or '').upper()).first()


@group_bp.route('/api/group-orders', methods=['POST'])
@jwt_required()
def create_group_order():
    uid = current_user_id()
    user = User.query.get(uid)
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404
    d = request.get_json(silent=True) or {}
    title = (d.get('title') or 'Group Order').strip()[:120] or 'Group Order'
    group = GroupOrder(join_code=_gen_join_code(), host_id=uid, title=title, status='open')
    db.session.add(group)
    db.session.flush()
    # Host is automatically the first participant.
    db.session.add(GroupOrderContribution(group_id=group.id, user_id=uid,
                                           participant_name=user.username, items='[]', subtotal=0))
    db.session.commit()
    return jsonify({'success': True, 'join_code': group.join_code,
                    'group': _group_state(group, uid)}), 201


@group_bp.route('/api/group-orders/<code>', methods=['GET'])
@jwt_required()
def get_group_order(code):
    group = _get_group_or_404(code)
    if not group:
        return jsonify({'success': False, 'message': 'Group order not found.'}), 404
    return jsonify({'success': True, 'group': _group_state(group, current_user_id())})


@group_bp.route('/api/group-orders/<code>/join', methods=['POST'])
@jwt_required()
def join_group_order(code):
    group = _get_group_or_404(code)
    if not group:
        return jsonify({'success': False, 'message': 'Group order not found.'}), 404
    if group.status != 'open':
        return jsonify({'success': False, 'message': 'This group order is no longer open.'}), 409
    uid = current_user_id()
    user = User.query.get(uid)
    if not GroupOrderContribution.query.filter_by(group_id=group.id, user_id=uid).first():
        db.session.add(GroupOrderContribution(group_id=group.id, user_id=uid,
                                               participant_name=user.username, items='[]', subtotal=0))
        db.session.commit()
    return jsonify({'success': True, 'group': _group_state(group, uid)})


@group_bp.route('/api/group-orders/<code>/items', methods=['PUT'])
@jwt_required()
def set_my_items(code):
    group = _get_group_or_404(code)
    if not group:
        return jsonify({'success': False, 'message': 'Group order not found.'}), 404
    if group.status != 'open':
        return jsonify({'success': False, 'message': 'This group order is locked.'}), 409
    uid = current_user_id()
    user = User.query.get(uid)
    items, subtotal, err = _clean_items((request.get_json(silent=True) or {}).get('items'))
    if err:
        return jsonify({'success': False, 'message': err}), 400
    contrib = GroupOrderContribution.query.filter_by(group_id=group.id, user_id=uid).first()
    if not contrib:
        contrib = GroupOrderContribution(group_id=group.id, user_id=uid, participant_name=user.username)
        db.session.add(contrib)
    contrib.items = json.dumps(items)
    contrib.subtotal = subtotal
    db.session.commit()
    return jsonify({'success': True, 'group': _group_state(group, uid)})


@group_bp.route('/api/group-orders/<code>/lock', methods=['POST'])
@jwt_required()
def set_group_lock(code):
    group = _get_group_or_404(code)
    if not group:
        return jsonify({'success': False, 'message': 'Group order not found.'}), 404
    if current_user_id() != group.host_id:
        return jsonify({'success': False, 'message': 'Only the host can lock or unlock the group.'}), 403
    if group.status in ('open', 'locked'):
        # Optional {"locked": false} re-opens it.
        want_locked = (request.get_json(silent=True) or {}).get('locked', True)
        group.status = 'locked' if want_locked else 'open'
        db.session.commit()
    return jsonify({'success': True, 'group': _group_state(group, current_user_id())})


@group_bp.route('/api/group-orders/<code>/place', methods=['POST'])
@jwt_required()
def place_group_order(code):
    group = _get_group_or_404(code)
    if not group:
        return jsonify({'success': False, 'message': 'Group order not found.'}), 404
    if current_user_id() != group.host_id:
        return jsonify({'success': False, 'message': 'Only the host can place the order.'}), 403
    if group.status == 'placed':
        return jsonify({'success': True, 'already': True, 'order_id': group.order_id,
                        'group': _group_state(group, current_user_id())})

    all_items, grand = [], 0.0
    for c in group.contributions:
        try:
            items = json.loads(c.items)
        except Exception:
            items = []
        for it in items:
            # Tag each line with who ordered it so the kitchen ticket is clear.
            all_items.append({'name': it['name'], 'price': it['price'],
                              'quantity': it['quantity'], 'for': c.participant_name})
        grand += c.subtotal
    if not all_items:
        return jsonify({'success': False, 'message': 'No items in the group order yet.'}), 400

    grand = round(grand, 2)
    # Collision-safe order_id (same pattern as customer checkout / POS).
    new_oid = None
    for _attempt in range(5):
        max_id = db.session.query(db.func.max(Order.order_id)).scalar()
        candidate = (max_id or 0) + 1 + _attempt
        if not Order.query.filter_by(order_id=candidate).first():
            new_oid = candidate
            break
    if new_oid is None:
        return jsonify({'success': False, 'message': 'Could not allocate an order number, please retry.'}), 503
    time_now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    db.session.add(Order(order_id=new_oid, user_id=group.host_id, items=json.dumps(all_items),
                         total=grand, coins_used=0, currency_paid=grand, date_time=time_now,
                         status='Pending', payment_method='Group / Split bill'))
    group.status = 'placed'
    group.order_id = new_oid
    db.session.commit()
    return jsonify({'success': True, 'order_id': new_oid,
                    'group': _group_state(group, current_user_id())})
