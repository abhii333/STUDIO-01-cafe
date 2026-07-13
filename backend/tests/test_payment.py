"""Razorpay signature verification (Standard Checkout, STEP 3)."""
import hmac
import hashlib
from conftest import register_user, bearer

SECRET = 'test_razorpay_secret'


def sign(order_id, payment_id, secret=SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def test_verify_payment_accepts_valid_signature(client):
    tok = register_user(client, 'payer1').get_json()['access_token']
    oid, pid = 'order_abc', 'pay_xyz'
    r = client.post('/api/verify-payment', headers=bearer(tok), json={
        'razorpay_order_id': oid, 'razorpay_payment_id': pid, 'razorpay_signature': sign(oid, pid)})
    assert r.status_code == 200 and r.get_json()['success'] is True


def test_verify_payment_rejects_bad_signature(client):
    tok = register_user(client, 'payer2').get_json()['access_token']
    r = client.post('/api/verify-payment', headers=bearer(tok), json={
        'razorpay_order_id': 'o', 'razorpay_payment_id': 'p', 'razorpay_signature': 'wrong'})
    assert r.status_code == 400


def test_verify_payment_requires_fields(client):
    tok = register_user(client, 'payer3').get_json()['access_token']
    assert client.post('/api/verify-payment', headers=bearer(tok), json={}).status_code == 400


def test_order_rejected_with_bad_signature(client):
    tok = register_user(client, 'payer4').get_json()['access_token']
    r = client.post('/api/order', headers=bearer(tok), json={
        'items': [{'name': 'Cold Brew Coffee', 'price': 250, 'quantity': 1}], 'total': 250, 'coins_to_use': 0,
        'payment_id': 'pay_fake', 'payment_method': 'Razorpay',
        'razorpay_order_id': 'order_fake', 'razorpay_signature': 'bad'})
    assert r.status_code == 400


def test_order_accepted_with_valid_signature(client):
    tok = register_user(client, 'payer5').get_json()['access_token']
    oid, pid = 'order_ok', 'pay_ok'
    r = client.post('/api/order', headers=bearer(tok), json={
        'items': [{'name': 'Cold Brew Coffee', 'price': 250, 'quantity': 1}], 'total': 250, 'coins_to_use': 0,
        'payment_id': pid, 'payment_method': 'Razorpay',
        'razorpay_order_id': oid, 'razorpay_signature': sign(oid, pid)})
    assert r.status_code == 200 and r.get_json().get('order_id')
