"""Social / engagement blueprint: recommendations, gallery photos,
share & earn, public events (+registration), and public offers.
"""
import json
from collections import Counter
from datetime import datetime

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy.orm import joinedload

from models import db, MenuItem, Order, Photo, User, Event, EventRegistration, Offer
from helpers import current_user_id, _offer_dict, _offer_is_current, _event_dict
from cache import api_cache, CACHE_TTL_EVENTS, CACHE_TTL_OFFERS, CACHE_TTL_PHOTOS

social_bp = Blueprint('social', __name__)


# ============================================================
# RECOMMENDATIONS
# ============================================================
# Rule-based scoring (no scikit-learn). Every recommendation blends:
#   - overall popularity,
#   - how often an item sells in the CURRENT time-of-day bucket,
#   - how often it sells on the CURRENT day of the week,
#   - and, for logged-in users, their personal item/category history.
# Weights are deliberately simple and explainable.
_WEEKDAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

# Scoring weights (per unit quantity in matching orders).
_W_POP = 1.0        # overall popularity
_W_TIME = 2.5       # ordered during the current time-of-day bucket
_W_DAY = 1.5        # ordered on the current weekday
_W_FAV_ITEM = 3.0   # this exact item is a personal favorite
_W_FAV_CAT = 1.5    # same category as a personal favorite

# Order timestamps are written as "%d-%m-%Y %I:%M %p" (see orders blueprint).
_ORDER_DT_FORMATS = ("%d-%m-%Y %I:%M %p", "%d-%m-%Y %H:%M")


def _time_bucket(hour):
    """Map an hour (0-23) to a (key, human-friendly reason phrase)."""
    if 5 <= hour < 11:
        return 'morning', 'Popular in the mornings'
    if 11 <= hour < 16:
        return 'afternoon', 'Popular in the afternoons'
    if 16 <= hour < 21:
        return 'evening', 'Popular in the evenings'
    return 'late_night', 'A late-night favorite'


def _parse_order_dt(s):
    for fmt in _ORDER_DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


@social_bp.route('/api/recommendations')
@jwt_required(optional=True)
def api_recommendations():
    now = datetime.now()
    cur_bucket, bucket_reason = _time_bucket(now.hour)
    cur_weekday = now.weekday()
    weekday_reason = f'A {_WEEKDAY_NAMES[cur_weekday]} favorite'

    all_items = MenuItem.query.options(joinedload(MenuItem.category)).all()
    items_by_name = {mi.name: mi for mi in all_items}
    sold_out = {mi.name for mi in all_items if mi.is_sold_out}

    # Global popularity + contextual (time-of-day / day-of-week) popularity.
    pop = Counter()
    time_pop = Counter()   # ordered during the current time bucket
    day_pop = Counter()    # ordered on the current weekday
    for o in Order.query.all():
        o_dt = _parse_order_dt(o.date_time)
        same_bucket = o_dt is not None and _time_bucket(o_dt.hour)[0] == cur_bucket
        same_weekday = o_dt is not None and o_dt.weekday() == cur_weekday
        try:
            for it in json.loads(o.items):
                base = it['name'].split(' [')[0]
                qty = it.get('quantity', 1)
                pop[base] += qty
                if same_bucket:
                    time_pop[base] += qty
                if same_weekday:
                    day_pop[base] += qty
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
                    mi = items_by_name.get(base)
                    if mi and mi.category:
                        fav_cats[mi.category.name] += it.get('quantity', 1)
            except Exception:
                pass

    scored = []
    for mi in all_items:
        if mi.name in sold_out:
            continue
        cat_name = mi.category.name if mi.category else ''
        # Weighted contributions from each signal.
        contrib = {
            'pop': pop.get(mi.name, 0) * _W_POP,
            'time': time_pop.get(mi.name, 0) * _W_TIME,
            'day': day_pop.get(mi.name, 0) * _W_DAY,
        }
        if uid:
            contrib['fav_item'] = fav_items.get(mi.name, 0) * _W_FAV_ITEM
            contrib['fav_cat'] = fav_cats.get(cat_name, 0) * _W_FAV_CAT
        score = sum(contrib.values())
        # Human-readable "why" = the strongest non-zero signal.
        top_signal = max(contrib, key=contrib.get)
        if contrib[top_signal] <= 0:
            reason = 'Popular on our menu'
        elif top_signal == 'fav_item':
            reason = 'One of your favorites'
        elif top_signal == 'fav_cat':
            reason = f'More {cat_name} you’ll love' if cat_name else 'Picked for you'
        elif top_signal == 'time':
            reason = bucket_reason
        elif top_signal == 'day':
            reason = weekday_reason
        else:
            reason = 'Trending now'
        scored.append((score, mi, reason))

    # Sort by score (desc); Python's stable sort keeps a consistent order for ties.
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:6]
    return jsonify([{'name': m.name, 'price': m.price, 'description': m.description,
                     'image_url': m.image_url, 'category': m.category.name if m.category else '',
                     'reason': reason} for _, m, reason in top])


# ============================================================
# PHOTOS + SHARE & EARN
# ============================================================
@social_bp.route('/api/photos')
def api_photos():
    cached = api_cache.get('photos')
    if cached:
        return cached
    photos = Photo.query.order_by(Photo.id.desc()).limit(30).all()
    resp = jsonify([{'id': p.id, 'image_url': p.image_url, 'caption': p.caption} for p in photos])
    api_cache.set('photos', resp, ttl=CACHE_TTL_PHOTOS)
    return resp


@social_bp.route('/api/user/orders/<int:oid>/share', methods=['POST'])
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
# EVENTS & WORKSHOPS (public)
# ============================================================
@social_bp.route('/api/events')
def api_events():
    cached = api_cache.get('events')
    if cached:
        return cached
    events = Event.query.filter_by(is_active=True).order_by(Event.date).all()
    resp = jsonify([_event_dict(e) for e in events])
    api_cache.set('events', resp, ttl=CACHE_TTL_EVENTS)
    return resp


@social_bp.route('/api/events/<int:eid>/register', methods=['POST'])
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


# ============================================================
# OFFERS / MEAL DEALS (public)
# ============================================================
@social_bp.route('/api/offers')
def api_offers():
    cached = api_cache.get('offers')
    if cached:
        return cached
    resp = jsonify([_offer_dict(o) for o in Offer.query.all() if _offer_is_current(o)])
    api_cache.set('offers', resp, ttl=CACHE_TTL_OFFERS)
    return resp
