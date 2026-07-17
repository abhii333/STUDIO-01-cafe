"""Database seeding + one-off data normalization.

These are idempotent: each ``seed_*`` returns early if its table already has
rows, so calling them on every boot is safe.
"""
import os
from datetime import date, timedelta

from sqlalchemy import inspect as sa_inspect, text

from models import db, Category, MenuItem, User, ReferralCode, Table, Badge, Event
from helpers import hash_password, PWD_METHOD
from services import IS_PRODUCTION


def ensure_schema():
    """Add columns introduced after the first release to existing databases.

    ``create_all()`` only creates missing *tables*, never missing *columns*, so
    for the few new nullable columns on the ``order`` table we ALTER them in when
    absent. Safe (only adds what's missing) and idempotent — works on SQLite and
    Postgres alike. ``order`` is a reserved word, hence the quoting.
    """
    try:
        insp = sa_inspect(db.engine)
        tables = set(insp.get_table_names())
        added = False

        if 'order' in tables:
            existing = {c['name'] for c in insp.get_columns('order')}
            additions = {
                'channel': 'VARCHAR(20)',
                'customer_label': 'VARCHAR(80)',
                'table_label': 'VARCHAR(20)',
                'upi_qr_id': 'VARCHAR(64)',
                'upi_qr_url': 'VARCHAR(500)',
            }
            for col, ddl in additions.items():
                if col not in existing:
                    db.session.execute(text(f'ALTER TABLE "order" ADD COLUMN {col} {ddl}'))
                    added = True

        if 'user' in tables:
            existing_user = {c['name'] for c in insp.get_columns('user')}
            if 'reset_token_expires' not in existing_user:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN reset_token_expires TIMESTAMP'))
                added = True

        if added:
            db.session.commit()

        # Create indexes on existing tables (create_all only adds them to NEW tables).
        # These are safe to run repeatedly — CREATE INDEX IF NOT EXISTS.
        index_stmts = [
            'CREATE INDEX IF NOT EXISTS ix_order_user_id ON "order" (user_id)',
            'CREATE INDEX IF NOT EXISTS ix_order_status ON "order" (status)',
            'CREATE INDEX IF NOT EXISTS ix_reservation_date ON reservation (date)',
            'CREATE INDEX IF NOT EXISTS ix_reservation_table_id ON reservation (table_id)',
            'CREATE INDEX IF NOT EXISTS ix_event_registration_event_id ON event_registration (event_id)',
            'CREATE INDEX IF NOT EXISTS ix_event_registration_user_id ON event_registration (user_id)',
        ]
        for stmt in index_stmts:
            try:
                db.session.execute(text(stmt))
            except Exception:
                pass  # index may already exist or table missing — safe to skip
        db.session.commit()

    except Exception as exc:  # pragma: no cover - never block boot on a migration hiccup
        db.session.rollback()
        print(f"[WARN] ensure_schema failed: {exc}")


# ---------------------------------------------------------------------------
# MENU — single source of truth for seed_menu() and reseed_menu().
# Prices are the launch prices (already include the +20% uplift over base).
# ---------------------------------------------------------------------------
_UNSPLASH = "https://images.unsplash.com/"
_WM = "https://commons.wikimedia.org/wiki/Special:FilePath/"

# Reusable, verified image URLs: Unsplash CDN (proven in prod) + stable
# Wikimedia Commons files (vegetarian-appropriate). All admin-editable later.
_IMG = {
    'espresso':    _UNSPLASH + "photo-1495474472287-4d71bcdd2085?w=600&q=80&fit=crop",
    'latte':       _UNSPLASH + "photo-1541167760496-1628856ab772?w=600&q=80&fit=crop",
    'iced_coffee': _UNSPLASH + "photo-1461023058943-07fcbe16d735?w=600&q=80&fit=crop",
    'iced_tea':    _UNSPLASH + "photo-1556679343-c7306c1976bc?w=600&q=80&fit=crop",
    'brownie':     _UNSPLASH + "photo-1564355808539-22fda35bed7e?w=600&q=80&fit=crop",
    'ganache':     _UNSPLASH + "photo-1551024506-0bccd828d307?w=600&q=80&fit=crop",
    'hot_choc':    _WM + "Hot-chocolate-1058197.jpg?width=600",
    'burger':      _WM + "Food_topic_image_Veggie_burger.jpg?width=600",
    'pizza':       _WM + "Margherita_PIzza_%28Unsplash%29.jpg?width=600",
    'fries':       _WM + "French_Fries.jpg?width=600",
    'garlic':      _WM + "Close-up_of_garlic_bread.jpg?width=600",
    'icecream':    _WM + "Ice_Cream_Dessert_%28Unsplash%29.jpg?width=600",
    'muffin':      _WM + "Muffin_%2823699389073%29.jpg?width=600",
    'fallback':    _UNSPLASH + "photo-1504674900247-0877df9cc836?w=600&q=80&fit=crop",
}

# category -> [(item_name, price, description, image_key), ...]
DEFAULT_MENU = [
    ("Hot Coffee", [
        ("Espresso", 119, "Pulled to order, rich crema.", 'espresso'),
        ("Americano", 143, "Espresso and hot water — honest and clean.", 'espresso'),
        ("Café Latte", 179, "Espresso with silky steamed milk.", 'latte'),
        ("Cappuccino", 179, "Equal parts espresso, milk, and microfoam.", 'latte'),
        ("Caramel Macchiato", 215, "Vanilla, espresso, and hand-drizzled caramel.", 'latte'),
    ]),
    ("Cold Coffee", [
        ("Cold Brew", 203, "Steeped slow for 18 hours.", 'iced_coffee'),
        ("Iced Latte", 215, "Espresso over ice with cold milk.", 'iced_coffee'),
        ("Cold Coffee Frappe", 239, "Blended cold, topped with whipped cream.", 'iced_coffee'),
        ("Choco Frappe", 251, "Cocoa and cold brew, blended.", 'iced_coffee'),
    ]),
    ("Beverages", [
        ("Hot Chocolate", 191, "Belgian cocoa with steamed milk.", 'hot_choc'),
        ("Iced Tea", 155, "Peach or lemon, brewed fresh.", 'iced_tea'),
    ]),
    ("Burgers", [
        ("Classic Veg Burger", 119, "Potato patty with house sauce.", 'burger'),
        ("Cheesy Veg Burger", 155, "Veg patty with double cheese.", 'burger'),
        ("Crispy Paneer Burger", 179, "Fried paneer with mint mayo.", 'burger'),
        ("Paneer Tikka Burger", 203, "Tandoor-charred paneer with mint chutney.", 'burger'),
        ("Cheese Overload Burger", 215, "Triple cheese with crisp onions.", 'burger'),
        ("Double Paneer Burger", 275, "Two patties with double cheese.", 'burger'),
    ]),
    ("Pizzas", [
        ("Margherita", 239, "Tomato, mozzarella, and basil. 8-inch medium.", 'pizza'),
        ("Farmhouse", 359, "Onion, capsicum, and mushroom. 8-inch medium.", 'pizza'),
        ("Peppy Paneer", 395, "Paneer, capsicum, and red pepper. 8-inch medium.", 'pizza'),
        ("Cheese Burst Veggie", 431, "Loaded veg with a molten cheese core. 8-inch medium.", 'pizza'),
        ("Paneer Tikka Pizza", 419, "Tandoori paneer, onion, and capsicum. 8-inch medium.", 'pizza'),
        ("BBQ Paneer", 455, "Smoky BBQ paneer with onion. 8-inch medium.", 'pizza'),
        ("Four Cheese", 479, "Mozzarella, cheddar, parmesan, and cream cheese. 8-inch medium.", 'pizza'),
    ]),
    ("Sides & Snacks", [
        ("French Fries", 119, "Salted and crisped to order.", 'fries'),
        ("Peri Peri Fries", 155, "Spiced and tangy.", 'fries'),
        ("Cheesy Garlic Bread", 179, "Toasted with molten cheese.", 'garlic'),
        ("Veg Nuggets (6 pc)", 155, "Crisp, served with dip.", 'fries'),
        ("Paneer Poppers (6 pc)", 191, "Crisp, served with dip.", 'fries'),
        ("Cheese Corn Balls (6 pc)", 215, "Crisp shell with a molten center.", 'fries'),
        ("Coleslaw", 95, "Fresh and creamy.", 'fallback'),
    ]),
    ("Combos", [
        ("No. 1 — Solo Value Meal", 299, "Any classic burger + fries + soft drink.", 'burger'),
        ("No. 2 — Pizza For Two", 539, "Any medium pizza + garlic bread + 2 cold drinks.", 'pizza'),
        ("No. 3 — Coffee & Bite", 275, "Any hot beverage + burger of your choice.", 'burger'),
        ("No. 4 — Family Feast", 959, "Large pizza + 6pc paneer poppers + fries + 4 drinks.", 'pizza'),
        ("No. 5 — Study Break", 335, "Cold coffee + fries + veg nuggets.", 'fries'),
        ("No. 6 — Study Squad", 1079, "Large pizza + garlic bread + 4 cold coffees. Serves 3–4.", 'pizza'),
    ]),
    ("Desserts", [
        ("Chocolate Brownie", 155, "Warm, fudgy, and dense. Eggless.", 'brownie'),
        ("Molten Lava Cake", 179, "Gooey chocolate center. Eggless.", 'ganache'),
        ("Soft Serve Cone", 71, "Vanilla or chocolate.", 'icecream'),
        ("Chocolate Chip Cookie", 59, "Baked in-house.", 'brownie'),
        ("Banana Muffin", 83, "Moist, baked fresh.", 'muffin'),
        ("Chocolate Muffin", 83, "Moist, baked fresh.", 'muffin'),
        ("Biscotti (2 pc)", 71, "Twice-baked, pairs with espresso.", 'ganache'),
    ]),
]


def _seed_menu_items():
    """Insert DEFAULT_MENU categories + items (assumes the menu tables are empty)."""
    for cat_name, items in DEFAULT_MENU:
        cat = Category(name=cat_name)
        db.session.add(cat)
        db.session.flush()
        db.session.add_all([
            MenuItem(name=name, price=price, description=desc,
                     image_url=_IMG.get(img_key, _IMG['fallback']), category_id=cat.id)
            for name, price, desc, img_key in items
        ])
    db.session.commit()


def seed_menu():
    """Seed the default menu ONLY on a brand-new database (no categories yet).

    After first boot the admin owns the menu via the dashboard; this never
    re-inserts deleted items. To intentionally REPLACE the whole menu on an
    existing database, run scripts/reseed_menu.py (which calls reseed_menu()).
    """
    if Category.query.first() is not None:
        return
    _seed_menu_items()


def reseed_menu():
    """DESTRUCTIVE: replace the entire menu with DEFAULT_MENU.

    Clears categories, menu items, offers (+ their items), and the daily
    special, then reseeds. Historical orders and reviews (which store item
    names as text) are left untouched. Returns the number of items seeded.
    """
    from models import Offer, OfferItem, Special
    # Delete children before parents to satisfy FK constraints (Postgres enforces).
    OfferItem.query.delete()
    Offer.query.delete()
    Special.query.delete()
    MenuItem.query.delete()
    Category.query.delete()
    db.session.commit()
    _seed_menu_items()
    try:
        from cache import api_cache
        api_cache.invalidate('menu', 'soldout', 'special', 'offers')
    except Exception:
        pass
    return sum(len(items) for _, items in DEFAULT_MENU)


def seed_admin():
    admin = User.query.filter_by(role='Admin').first()
    admin_password = os.environ.get('ADMIN_PASSWORD')
    if not admin_password and not IS_PRODUCTION:
        admin_password = 'admin123'  # local-dev convenience only
    if admin:
        # Re-hash to the faster method so admin login isn't slow on low-CPU hosting.
        if admin_password and not admin.password.startswith(PWD_METHOD):
            admin.password = hash_password(admin_password)
            db.session.commit()
        return
    if not admin_password:
        print("[WARN] ADMIN_PASSWORD not set in production; skipping admin seed.")
        return
    admin = User(username='admin', email=os.environ.get('ADMIN_EMAIL', 'admin@studio01.com'),
                 password=hash_password(admin_password), role='Admin')
    db.session.add(admin)
    db.session.flush()
    db.session.add(ReferralCode(code='ADMIN01', owner_id=admin.id))
    db.session.commit()


def seed_tables():
    if Table.query.first() is not None:
        return
    layout = [
        ('T1', 2, 'indoor'), ('T2', 2, 'indoor'), ('T3', 2, 'indoor'), ('T4', 2, 'indoor'),
        ('T5', 4, 'indoor'), ('T6', 4, 'indoor'),
        ('P1', 4, 'terrace'), ('P2', 6, 'terrace'),
        ('G1', 4, 'outdoor'), ('G2', 6, 'outdoor'),
    ]
    db.session.add_all([
        Table(table_number=num, capacity=cap, location=loc, is_available=True)
        for num, cap, loc in layout
    ])
    db.session.commit()


def seed_badges():
    if Badge.query.first() is not None:
        return
    badges = [
        ('first_order', 'First Order', 'Placed your very first order', 'lucide:sparkles', 'order_count', 1),
        ('coffee_lover', 'Coffee Lover', 'Completed 10 orders', 'lucide:coffee', 'order_count', 10),
        ('big_spender', 'Big Spender', 'Spent Rs.5000 in total', 'lucide:gem', 'total_spend', 5000),
        ('week_warrior', 'Week Warrior', '7-day ordering streak', 'lucide:flame', 'streak', 7),
        ('early_bird', 'Early Bird', 'Ordered before 9 AM', 'lucide:sunrise', 'early_bird', 1),
        ('review_master', 'Review Master', 'Wrote 5 reviews', 'lucide:star', 'review_count', 5),
    ]
    db.session.add_all([
        Badge(key=key, name=name, description=desc, icon=icon,
              requirement_type=rt, requirement_value=rv)
        for key, name, desc, icon, rt, rv in badges
    ])
    db.session.commit()


def seed_events():
    if Event.query.first() is not None:
        return
    # Dates are relative to "today" so freshly-seeded databases always show
    # upcoming events (never stale past dates). The public /api/events endpoint
    # additionally hides any event whose date has already passed.
    today = date.today()
    events = [
        ('Coffee Brewing Workshop', 'Master pour-over, French press, and cold brew with our head barista.',
         (today + timedelta(days=14)).isoformat(), '11:00', 90, 12, 799, 'https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600&fit=crop'),
        ('Latte Art Masterclass', 'Learn to pour hearts, rosettas, and tulips like a pro.',
         (today + timedelta(days=21)).isoformat(), '16:00', 60, 10, 599, 'https://images.unsplash.com/photo-1541167760496-1628856ab772?w=600&fit=crop'),
        ('Vegan Baking Day', 'Hands-on session baking plant-based pastries and desserts.',
         (today + timedelta(days=35)).isoformat(), '10:00', 120, 8, 999, 'https://images.unsplash.com/photo-1509440159596-0249088772ff?w=600&fit=crop'),
    ]
    db.session.add_all([
        Event(title=title, description=desc, date=date, time=time, duration_minutes=dur,
              capacity=cap, price=price, image_url=img, is_active=True)
        for title, desc, date, time, dur, cap, price, img in events
    ])
    db.session.commit()


def fix_broken_menu_images():
    """Repair menu items still pointing at image URLs that 404.

    Runs on boot so already-seeded databases (where seed_menu skips existing
    items) get the corrected images without a manual re-seed. Only rows whose
    image_url is a known-broken URL are touched, so admin-edited images are safe.
    """
    # Old (404) URL -> working replacement.
    replacements = {
        # Turmeric Oat Latte + Almond Saffron Milk both used this dead Unsplash photo.
        "https://images.unsplash.com/photo-1578899544867-3df4946b9e27?w=400&fit=crop":
            "https://images.unsplash.com/photo-1541167760496-1628856ab772?w=400&fit=crop",
        # Gulab Jamun dead Unsplash photo.
        "https://images.unsplash.com/photo-1666190070080-5dee67e23cf0?w=400&fit=crop":
            "https://upload.wikimedia.org/wikipedia/commons/5/56/Gulab_Jamun.jpg",
    }
    # A few items need item-specific images (not just a 1:1 URL swap).
    by_name = {
        "Almond Saffron Milk": "https://upload.wikimedia.org/wikipedia/commons/3/38/Glass_of_milk.jpg",
        "Classic Gulab Jamun": "https://upload.wikimedia.org/wikipedia/commons/5/56/Gulab_Jamun.jpg",
        "Turmeric Oat Latte": "https://images.unsplash.com/photo-1541167760496-1628856ab772?w=400&fit=crop",
    }
    broken_urls = set(replacements.keys())
    changed = False
    for item in MenuItem.query.all():
        # Only fix rows that still carry a known-broken URL (or are empty).
        if item.image_url in broken_urls or not item.image_url:
            new_url = by_name.get(item.name) or replacements.get(item.image_url)
            if new_url and new_url != item.image_url:
                item.image_url = new_url
                changed = True
    if changed:
        db.session.commit()


def normalize_referral_codes():
    """Make each customer's referral code match their username (fixes older uppercased codes)."""
    changed = False
    for u in User.query.filter(User.role != 'Admin').all():
        ref = ReferralCode.query.filter_by(owner_id=u.id).first()
        desired = u.username[:10]
        if ref and ref.code != desired:
            clash = ReferralCode.query.filter(db.func.lower(ReferralCode.code) == desired.lower(),
                                              ReferralCode.owner_id != u.id).first()
            if not clash:
                ref.code = desired
                changed = True
    if changed:
        db.session.commit()
