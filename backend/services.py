"""External integrations (all optional) and small runtime flags.

Everything here degrades gracefully: if a package or credential is missing the
corresponding client is ``None`` and the app keeps running.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import razorpay
except Exception:
    razorpay = None

try:
    import cloudinary
    import cloudinary.uploader
except Exception:
    cloudinary = None

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    SENTRY_DSN = os.environ.get('SENTRY_DSN')
    if SENTRY_DSN:
        sentry_sdk.init(dsn=SENTRY_DSN, integrations=[FlaskIntegration()], traces_sample_rate=0.1)
except Exception:
    sentry_sdk = None


def maybe_capture_exception(exc):
    try:
        if sentry_sdk is not None:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def maybe_capture_message(msg, level='error'):
    try:
        if sentry_sdk is not None:
            sentry_sdk.capture_message(msg, level=level)
    except Exception:
        pass


IS_PRODUCTION = os.environ.get('FLASK_ENV') == 'production' or os.environ.get('PRODUCTION') == '1'

# Cloudinary (safe to configure even with blank creds)
if cloudinary is not None:
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
        api_key=os.environ.get('CLOUDINARY_API_KEY', ''),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET', ''),
    )

# Razorpay client
razorpay_key_id = os.environ.get('RAZORPAY_KEY_ID')
razorpay_key_secret = os.environ.get('RAZORPAY_KEY_SECRET')
razorpay_init_error = None
if razorpay is not None and razorpay_key_id and razorpay_key_secret:
    try:
        razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))
    except Exception as exc:
        razorpay_client = None
        razorpay_init_error = str(exc)
else:
    razorpay_client = None
    razorpay_init_error = 'Razorpay credentials are missing.' if not (razorpay_key_id and razorpay_key_secret) else None

# Secret used to verify incoming Razorpay webhooks (set one in the Razorpay
# dashboard when you add the webhook, and mirror it here as an env var).
razorpay_webhook_secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET')
