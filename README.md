# STUDIO 01 — Cafe Ordering App

This is a Flask-based cafe ordering application with admin dashboards, menu management, loyalty coins, and Razorpay integration.

## Local setup

1. Create a Python virtual environment and activate it (macOS/Linux):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. (Optional) Create a `.env` file with values:

```
SECRET_KEY=change-me
DATABASE_URL=sqlite:///cafe.db
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

4. Run the app:

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

The app will seed an initial admin user: `admin` / `admin123`.

## Hosting

- A `Procfile` is included for platforms like Heroku.
- A `Dockerfile` is provided to build a container for deployment.
- For automated deployments, add a GitHub Actions workflow or connect the repo to Render/Heroku.

## Notes

- Razorpay and Cloudinary are optional — the app will start without them but payment/image upload features will be disabled/mocked.
- Make sure to set `SECRET_KEY` in production and enable secure session cookies.
