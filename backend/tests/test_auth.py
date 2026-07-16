"""Task 2 verification: JWT auth + authorization."""
from conftest import register_user, bearer


def test_register_returns_tokens(client):
    r = register_user(client)
    assert r.status_code == 201
    d = r.get_json()
    assert d['access_token'] and d['refresh_token']
    assert d['user']['username'] == 'alice'


def test_duplicate_username_rejected(client):
    register_user(client)
    assert register_user(client).status_code == 409


def test_login_success_and_failure(client):
    register_user(client, 'bob')
    ok = client.post('/api/auth/login', json={'username': 'bob', 'password': 'test1234'})
    assert ok.status_code == 200 and ok.get_json()['access_token']
    bad = client.post('/api/auth/login', json={'username': 'bob', 'password': 'nope'})
    assert bad.status_code == 401


def test_protected_requires_token(client):
    assert client.get('/api/user/profile').status_code == 401
    tok = register_user(client, 'carol').get_json()['access_token']
    r = client.get('/api/user/profile', headers=bearer(tok))
    assert r.status_code == 200 and r.get_json()['username'] == 'carol'


def test_admin_route_forbidden_for_customer(client):
    tok = register_user(client, 'dave').get_json()['access_token']
    assert client.get('/api/admin/orders', headers=bearer(tok)).status_code == 403


def test_admin_login_can_access_admin_route(client):
    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'testadminpw'})
    assert login.status_code == 200
    tok = login.get_json()['access_token']
    assert client.get('/api/admin/orders', headers=bearer(tok)).status_code == 200


def test_refresh_issues_new_access_token(client):
    refresh = register_user(client, 'erin').get_json()['refresh_token']
    r = client.post('/api/auth/refresh', headers=bearer(refresh))
    assert r.status_code == 200 and r.get_json()['access_token']
