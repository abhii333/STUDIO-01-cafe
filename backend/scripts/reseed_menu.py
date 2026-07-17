#!/usr/bin/env python
"""Replace the STUDIO 01 menu with the current DEFAULT_MENU (DESTRUCTIVE).

Wipes categories, menu items, offers (+ their items) and the daily special,
then reseeds from seed.DEFAULT_MENU. Historical orders and reviews are kept
(they store item names as text, so they are unaffected).

Usage:
    cd backend && python scripts/reseed_menu.py           # prompts for confirmation
    cd backend && RESEED_YES=1 python scripts/reseed_menu.py   # no prompt (CI/deploy)

On Render: open the backend service "Shell" and run the same command. It uses
the same DATABASE_URL as the app, so it updates the live (Neon) menu.
"""
import os
import sys

# Make the backend package importable when run directly as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db  # noqa: E402
from seed import reseed_menu, DEFAULT_MENU  # noqa: E402


def main():
    total = sum(len(items) for _, items in DEFAULT_MENU)
    print(f"This will REPLACE the entire menu with {total} items across "
          f"{len(DEFAULT_MENU)} categories, and delete existing offers + the daily special.")

    confirmed = os.environ.get('RESEED_YES') == '1'
    if not confirmed:
        if sys.stdin.isatty():
            confirmed = input("Continue? [y/N] ").strip().lower() in ('y', 'yes')
        else:
            print("Refusing to run non-interactively. Re-run with RESEED_YES=1 to confirm.")
            return

    if not confirmed:
        print("Aborted — nothing changed.")
        return

    with app.app_context():
        db.create_all()  # ensure all tables exist (older/edge DBs may lag the schema)
        n = reseed_menu()
    print(f"Done — menu replaced with {n} items.")


if __name__ == '__main__':
    main()
