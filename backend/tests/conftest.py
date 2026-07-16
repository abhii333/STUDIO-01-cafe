"""Shared pytest fixtures. Env is configured BEFORE importing the app so it
uses a throwaway SQLite database and predictable secrets."""
import os
import tempfile

os.environ['AUTO_INIT_DB'] = '0'
os.environ.setdefault('JWT_SECRET', 'test-jwt-secret-key-at-least-32-bytes-long')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-at-least-32-bytes-long!!')
os.environ['ADMIN_PASSWORD'] = 'testadminpw'
os.environ['RAZORPAY_KEY_SECRET'] = 'test_razorpay_secret'
# Disable rate limiting during tests: the suite makes >5 login calls from the
# same client address, which would otherwise trip the "5 per minute" limit.
os.environ['RATELIMIT_ENABLED'] = '0'

_db_fd, _db_path = tempfile.mkstemp(suffix='.db')
os.environ['DATABASE_URL'] = 'sqlite:///' + _db_path

import pytest  # noqa: E402
from app import (app as flask_app, db, seed_menu, seed_admin,  # noqa: E402
                 seed_tables, seed_badges, seed_events)


@pytest.fixture(autouse=True)
def app_context():
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        seed_menu()
        seed_tables()
        seed_badges()
        seed_events()
        seed_admin()
        yield
        db.session.remove()


@pytest.fixture
def client():
    return flask_app.test_client()


def register_user(client, username='alice', password='test1234'):
    return client.post('/api/auth/register', json={
        'username': username, 'email': f'{username}@example.com', 'password': password,
    })


def bearer(token):
    return {'Authorization': f'Bearer {token}'}
