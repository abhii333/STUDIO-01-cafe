"""Task 1 verification: config + seeding."""
from app import _normalize_db_url, seed_menu, Category


def test_postgres_scheme_rewrite():
    assert _normalize_db_url('postgres://u:p@host:5432/db') == 'postgresql://u:p@host:5432/db'


def test_scheme_rewrite_leaves_others_untouched():
    assert _normalize_db_url('postgresql://x') == 'postgresql://x'
    assert _normalize_db_url('sqlite:///cafe.db') == 'sqlite:///cafe.db'
    assert _normalize_db_url(None) is None


def test_seed_menu_is_idempotent():
    before = Category.query.count()
    assert before > 0            # fixture already seeded
    seed_menu()                  # second call must not duplicate
    assert Category.query.count() == before
