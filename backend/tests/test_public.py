"""Public (unauthenticated) endpoints."""


def test_health_returns_json(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.get_json()['status'] == 'ok'


def test_menu_has_items(client):
    r = client.get('/api/menu')
    assert r.status_code == 200
    data = r.get_json()
    assert 'menu' in data and len(data['menu']) > 0
    assert 'customizations' in data


def test_config_reports_razorpay_flag(client):
    r = client.get('/api/config')
    assert r.status_code == 200
    assert 'razorpay_available' in r.get_json()


def test_reviews_and_soldout_ok(client):
    assert client.get('/api/reviews').status_code == 200
    assert client.get('/api/soldout').status_code == 200
    assert client.get('/api/special').status_code == 200
