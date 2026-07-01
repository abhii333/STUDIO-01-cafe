"""Tests for the new features: tables/booking, events, offers, menu CRUD,
share & earn, recommendations, and gamification."""
from conftest import register_user, bearer


def admin_token(client):
    return client.post('/api/auth/login', json={'username': 'admin', 'password': 'testadminpw'}).get_json()['access_token']


def cust_token(client, u='feat'):
    return register_user(client, u).get_json()['access_token']


def place_order(client, tok, name='Cold Brew Coffee', price=250):
    return client.post('/api/order', headers=bearer(tok), json={
        'items': [{'name': name, 'price': price, 'quantity': 1}],
        'total': price, 'coins_to_use': 0, 'payment_method': 'Cash at counter'})


# ---- Tables / booking ----
def test_tables_seeded(client):
    tables = client.get('/api/tables').get_json()
    assert len(tables) >= 10
    assert all('available' in t and 'location' in t for t in tables)


def test_double_booking_is_prevented(client):
    tok = cust_token(client, 'booker')
    tid = client.get('/api/tables').get_json()[0]['id']
    b1 = client.post('/api/book', headers=bearer(tok), json={
        'name': 'A', 'email': 'a@x.com', 'date': '2026-03-01', 'time': '19:00', 'guests': '2', 'table_id': tid})
    assert b1.status_code == 200
    b2 = client.post('/api/book', headers=bearer(tok), json={
        'name': 'B', 'email': 'b@x.com', 'date': '2026-03-01', 'time': '19:00', 'guests': '2', 'table_id': tid})
    assert b2.status_code == 409
    avail = client.get('/api/tables?date=2026-03-01&time=19:00').get_json()
    assert next(t for t in avail if t['id'] == tid)['available'] is False


# ---- Events ----
def test_event_register_and_duplicate(client):
    events = client.get('/api/events').get_json()
    assert len(events) >= 3
    eid = events[0]['id']
    tok = cust_token(client, 'eventgoer')
    assert client.post(f'/api/events/{eid}/register', headers=bearer(tok)).status_code == 200
    assert client.post(f'/api/events/{eid}/register', headers=bearer(tok)).status_code == 409


def test_event_capacity_sold_out(client):
    atok = admin_token(client)
    eid = client.post('/api/admin/events', headers=bearer(atok),
                      json={'title': 'Tiny', 'date': '2026-04-01', 'time': '10:00', 'capacity': 1}).get_json()['id']
    assert client.post(f'/api/events/{eid}/register', headers=bearer(cust_token(client, 'cap1'))).status_code == 200
    assert client.post(f'/api/events/{eid}/register', headers=bearer(cust_token(client, 'cap2'))).status_code == 409


# ---- Offers ----
def test_offer_crud_and_public_visibility(client):
    atok = admin_token(client)
    oid = client.post('/api/admin/offers', headers=bearer(atok),
                      json={'title': 'Combo Deal', 'offer_type': 'combo', 'combo_price': 400, 'is_active': True}).get_json()['id']
    assert any(o['id'] == oid for o in client.get('/api/offers').get_json())
    client.put(f'/api/admin/offers/{oid}', headers=bearer(atok), json={'is_active': False})
    assert not any(o['id'] == oid for o in client.get('/api/offers').get_json())
    assert client.delete(f'/api/admin/offers/{oid}', headers=bearer(atok)).status_code == 200


# ---- Menu CRUD ----
def test_menu_item_crud_reflects_on_storefront(client):
    atok = admin_token(client)
    cid = client.get('/api/admin/categories', headers=bearer(atok)).get_json()[0]['id']
    iid = client.post('/api/admin/menu-items', headers=bearer(atok),
                      json={'name': 'Test Latte', 'price': 199, 'description': 'd', 'category_id': cid}).get_json()['item']['id']
    menu = client.get('/api/menu').get_json()['menu']
    assert any('Test Latte' in items for items in menu.values())
    assert client.delete(f'/api/admin/menu-items/{iid}', headers=bearer(atok)).status_code == 200


def test_menu_crud_requires_admin(client):
    tok = cust_token(client, 'notadmin')
    assert client.post('/api/admin/menu-items', headers=bearer(tok),
                       json={'name': 'x', 'price': 1, 'category_id': 1}).status_code == 403


# ---- Share & earn ----
def test_share_reward_granted_once(client):
    tok = cust_token(client, 'sharer')
    oid = place_order(client, tok).get_json()['order_id']
    assert client.post(f'/api/user/orders/{oid}/share', headers=bearer(tok)).get_json()['coins_awarded'] == 10
    assert client.post(f'/api/user/orders/{oid}/share', headers=bearer(tok)).get_json()['coins_awarded'] == 0


# ---- Recommendations ----
def test_recommendations_returns_list(client):
    r = client.get('/api/recommendations')
    assert r.status_code == 200 and isinstance(r.get_json(), list)


# ---- Gamification ----
def test_first_order_badge_and_profile_badges(client):
    tok = cust_token(client, 'badgeuser')
    resp = place_order(client, tok).get_json()
    assert 'new_badges' in resp
    assert any(b['key'] == 'first_order' for b in resp['new_badges'])
    prof = client.get('/api/user/profile', headers=bearer(tok)).get_json()
    assert 'current_streak' in prof and prof['current_streak'] == 1
    assert any(b['earned'] and b['key'] == 'first_order' for b in prof['badges'])
