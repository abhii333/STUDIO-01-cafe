"""Order creation via JWT (coins + payment method)."""
from conftest import register_user, bearer


def _token(client, username='oscar'):
    return register_user(client, username).get_json()['access_token']


def test_order_requires_auth(client):
    assert client.post('/api/order', json={'items': [], 'total': 0}).status_code == 401


def test_order_records_payment_method_and_awards_coins(client):
    tok = _token(client)
    r = client.post('/api/order', headers=bearer(tok), json={
        'items': [{'name': 'Cold Brew', 'price': 203, 'quantity': 1}],
        'total': 203, 'coins_to_use': 0, 'payment_id': None, 'payment_method': 'Cash at counter',
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d['payment_method'] == 'Cash at counter'
    assert d['offline_payment'] is True
    assert d['coins_earned'] >= 1
    assert d['currency_paid'] == 203


def test_coins_rejected_for_non_redeemable_item(client):
    # New users have 0 coins, so requesting coins should be blocked before category checks.
    tok = _token(client, 'peggy')
    r = client.post('/api/order', headers=bearer(tok), json={
        'items': [{'name': 'Four Cheese', 'price': 479, 'quantity': 1}],
        'total': 479, 'coins_to_use': 10, 'payment_method': 'Cash at counter',
    })
    assert r.status_code == 400
