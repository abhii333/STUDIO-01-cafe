"""Database seeding + one-off data normalization.

These are idempotent: each ``seed_*`` returns early if its table already has
rows, so calling them on every boot is safe.
"""
import os

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
    except Exception as exc:  # pragma: no cover - never block boot on a migration hiccup
        db.session.rollback()
        print(f"[WARN] ensure_schema failed: {exc}")


def seed_menu():
    """Seed menu categories and items. Idempotent — skips items that already exist.

    Category order: Starters → Soups & Salads → Gourmet Sandwiches → Main Course → Desserts → Beverages
    (menu starts from Starters, beverages last).
    """
    # Images — real Unsplash photos for each dish.
    default_imgs = {
        # Starters
        "Tandoori Paneer Tikka": "https://images.unsplash.com/photo-1567188040759-fb8a883dc6d8?w=400&fit=crop",
        "Hara Bhara Kebab": "https://images.unsplash.com/photo-1601050690117-94f5f6fa8bd7?w=400&fit=crop",
        "Crispy Chilli Baby Corn": "https://images.unsplash.com/photo-1626200419199-391ae4be7a41?w=400&fit=crop",
        "Truffle Mushroom Bruschetta": "https://images.unsplash.com/photo-1572695157366-5e585ab2b69f?w=400&fit=crop",
        "Edamame Hummus Platter": "https://images.unsplash.com/photo-1577805947697-89e18249d767?w=400&fit=crop",
        # Soups & Salads
        "Roasted Tomato Basil Soup": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=400&fit=crop",
        "Lemon Coriander Soup": "https://images.unsplash.com/photo-1604152135912-04a022e23696?w=400&fit=crop",
        "Mediterranean Greek Salad": "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?w=400&fit=crop",
        "Quinoa & Pomegranate Salad": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=400&fit=crop",
        # Gourmet Sandwiches
        "Spinach, Corn & Cheese Panini": "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?w=400&fit=crop",
        "Pesto Caprese Sandwich": "https://images.unsplash.com/photo-1539252554453-80ab65ce3586?w=400&fit=crop",
        "Bombay Masala Grilled Toast": "https://images.unsplash.com/photo-1528736235302-52922df5c122?w=400&fit=crop",
        "Caprese Ciabatta": "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?w=400&fit=crop",
        "Smoked Gouda & Pear Melt": "https://images.unsplash.com/photo-1528736235302-52922df5c122?w=400&fit=crop",
        # Main Course
        "Paneer Butter Masala": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=400&fit=crop",
        "Dal Makhani": "https://images.unsplash.com/photo-1546833999-b9f581a1996d?w=400&fit=crop",
        "Vegetable Dum Biryani": "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?w=400&fit=crop",
        "Roasted Vegetable Risotto": "https://images.unsplash.com/photo-1476124369491-e7addf5db371?w=400&fit=crop",
        "Paneer Roulade": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=400&fit=crop",
        "Thai Green Curry Bowl": "https://images.unsplash.com/photo-1455619452474-d2be8b1e70cd?w=400&fit=crop",
        # Desserts
        "Sizzling Walnut Brownie": "https://images.unsplash.com/photo-1564355808539-22fda35bed7e?w=400&fit=crop",
        "Classic Gulab Jamun": "https://upload.wikimedia.org/wikipedia/commons/5/56/Gulab_Jamun.jpg",
        "Rasmalai": "https://images.unsplash.com/photo-1645177628172-a94c1f96e6db?w=400&fit=crop",
        "Dark Chocolate Ganache Tart": "https://images.unsplash.com/photo-1551024506-0bccd828d307?w=400&fit=crop",
        "Saffron Infused Panna Cotta": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=400&fit=crop",
        # Beverages
        "Classic Cold Coffee": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=400&fit=crop",
        "Fresh Lime Soda": "https://images.unsplash.com/photo-1556881286-fc6915169721?w=400&fit=crop",
        "Almond Saffron Milk": "https://upload.wikimedia.org/wikipedia/commons/3/38/Glass_of_milk.jpg",
        "Cold Brew Coffee": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=400&fit=crop",
        "Hibiscus Iced Tea": "https://images.unsplash.com/photo-1556679343-c7306c1976bc?w=400&fit=crop",
        "Turmeric Oat Latte": "https://images.unsplash.com/photo-1541167760496-1628856ab772?w=400&fit=crop",
    }

    # Ordered dict — categories seeded in this order so the frontend menu starts from Starters.
    menu_data = [
        ("Starters", [
            ("Tandoori Paneer Tikka", 350, "Marinated cottage cheese cubes roasted in a tandoor."),
            ("Hara Bhara Kebab", 280, "Spiced patties made from spinach, peas, and potatoes."),
            ("Crispy Chilli Baby Corn", 320, "Fried baby corn tossed in a spicy, tangy sauce."),
            ("Truffle Mushroom Bruschetta", 450, "Wild mushrooms, truffle oil, balsamic glaze on sourdough."),
            ("Edamame Hummus Platter", 490, "Creamy edamame puree, crudités, warm za'atar flatbread."),
        ]),
        ("Soups & Salads", [
            ("Roasted Tomato Basil Soup", 250, "A rich, warm soup served with a drizzle of cream."),
            ("Lemon Coriander Soup", 220, "A clear, refreshing vegetable broth."),
            ("Mediterranean Greek Salad", 380, "Fresh cucumbers, tomatoes, olives, and feta tossed in olive oil."),
            ("Quinoa & Pomegranate Salad", 480, "Organic quinoa, arugula, pomegranate seeds, toasted walnuts."),
        ]),
        ("Gourmet Sandwiches", [
            ("Spinach, Corn & Cheese Panini", 420, "Grilled to perfection in artisanal bread."),
            ("Pesto Caprese Sandwich", 450, "Fresh mozzarella, tomatoes, and basil pesto."),
            ("Bombay Masala Grilled Toast", 350, "Spiced potato filling with green chutney and cheese."),
            ("Caprese Ciabatta", 550, "Fresh mozzarella, heirloom tomatoes, basil pesto, arugula."),
            ("Smoked Gouda & Pear Melt", 580, "Caramelized pears, smoked gouda, arugula, honey drizzle on rye."),
        ]),
        ("Main Course", [
            ("Paneer Butter Masala", 420, "Cottage cheese in a rich, creamy tomato gravy."),
            ("Dal Makhani", 350, "Slow-cooked black lentils finished with butter and cream."),
            ("Vegetable Dum Biryani", 450, "Fragrant basmati rice cooked with mixed vegetables and whole spices."),
            ("Roasted Vegetable Risotto", 750, "Arborio rice, seasonal roasted vegetables, parmesan crisp."),
            ("Paneer Roulade", 680, "Paneer stuffed with spinach and nuts, served with saffron gravy."),
            ("Thai Green Curry Bowl", 720, "Fragrant coconut-based curry, bamboo shoots, tofu, jasmine rice."),
        ]),
        ("Desserts", [
            ("Sizzling Walnut Brownie", 320, "Served warm on a hot plate."),
            ("Classic Gulab Jamun", 180, "Deep-fried milk solids soaked in sugar syrup."),
            ("Rasmalai", 220, "Soft paneer discs soaked in thickened, sweetened milk."),
            ("Dark Chocolate Ganache Tart", 350, "70% cocoa, sea salt, raspberry coulis."),
            ("Saffron Infused Panna Cotta", 380, "Velvety Italian cream, saffron thread, pistachio crumble."),
        ]),
        ("Beverages", [
            ("Classic Cold Coffee", 220, "Blended sweet iced coffee."),
            ("Fresh Lime Soda", 150, "Available sweet, salted, or mixed."),
            ("Almond Saffron Milk", 280, "Served chilled or warm."),
            ("Cold Brew Coffee", 250, "Slow-steeped 12-hour extraction."),
            ("Hibiscus Iced Tea", 220, "Floral, tart, and refreshing."),
            ("Turmeric Oat Latte", 280, "Golden milk with ginger, cinnamon, and creamy oat milk."),
        ]),
    ]

    fallback = "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400&fit=crop"

    # Collect existing item names so we don't duplicate anything on re-seeds.
    existing_names = {mi.name for mi in MenuItem.query.all()}

    for cat_name, items in menu_data:
        # Get or create category.
        cat = Category.query.filter_by(name=cat_name).first()
        if not cat:
            cat = Category(name=cat_name)
            db.session.add(cat)
            db.session.flush()
        for item_name, price, desc in items:
            if item_name in existing_names:
                continue  # skip duplicates
            db.session.add(MenuItem(
                name=item_name, price=price, description=desc,
                image_url=default_imgs.get(item_name, fallback), category_id=cat.id
            ))
            existing_names.add(item_name)
    db.session.commit()


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
    for num, cap, loc in layout:
        db.session.add(Table(table_number=num, capacity=cap, location=loc, is_available=True))
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
    for key, name, desc, icon, rt, rv in badges:
        db.session.add(Badge(key=key, name=name, description=desc, icon=icon,
                             requirement_type=rt, requirement_value=rv))
    db.session.commit()


def seed_events():
    if Event.query.first() is not None:
        return
    events = [
        ('Coffee Brewing Workshop', 'Master pour-over, French press, and cold brew with our head barista.',
         '2026-01-15', '11:00', 90, 12, 799, 'https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600&fit=crop'),
        ('Latte Art Masterclass', 'Learn to pour hearts, rosettas, and tulips like a pro.',
         '2026-01-22', '16:00', 60, 10, 599, 'https://images.unsplash.com/photo-1541167760496-1628856ab772?w=600&fit=crop'),
        ('Vegan Baking Day', 'Hands-on session baking plant-based pastries and desserts.',
         '2026-02-05', '10:00', 120, 8, 999, 'https://images.unsplash.com/photo-1509440159596-0249088772ff?w=600&fit=crop'),
    ]
    for title, desc, date, time, dur, cap, price, img in events:
        db.session.add(Event(title=title, description=desc, date=date, time=time, duration_minutes=dur,
                             capacity=cap, price=price, image_url=img, is_active=True))
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
