"""Public webhooks (no auth) — currently Razorpay payment notifications.

Razorpay POSTs here when a QR code is paid. We verify the signature over the
raw request body, then auto-mark the matching order Paid. This is what makes
POS UPI orders flip to 'Paid' on the staff screen without anyone tapping.
"""
import hmac
import hashlib
import json

from flask import Blueprint, request, jsonify

from models import db, Order, OrderAudit
from services import razorpay_webhook_secret, maybe_capture_exception

webhooks_bp = Blueprint('webhooks', __name__)


def _verify(raw_body, signature, secret):
    if not (secret and signature):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


@webhooks_bp.route('/api/webhooks/razorpay', methods=['POST'])
def razorpay_webhook():
    raw = request.get_data()  # exact bytes — required for HMAC verification
    signature = request.headers.get('X-Razorpay-Signature', '')

    if not razorpay_webhook_secret:
        # Not configured yet — ack so Razorpay stops retrying, but do nothing.
        return jsonify({'status': 'ignored', 'reason': 'webhook not configured'}), 200
    if not _verify(raw, signature, razorpay_webhook_secret):
        return jsonify({'status': 'invalid signature'}), 400

    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception:
        return jsonify({'status': 'bad payload'}), 400

    if data.get('event') == 'qr_code.credited':
        try:
            payload = data.get('payload', {}) or {}
            qr_entity = (payload.get('qr_code', {}) or {}).get('entity', {}) or {}
            pay_entity = (payload.get('payment', {}) or {}).get('entity', {}) or {}
            order_ref = (qr_entity.get('notes') or {}).get('order_ref')
            qr_id = qr_entity.get('id')

            order = None
            if order_ref:
                try:
                    order = Order.query.filter_by(order_id=int(order_ref)).first()
                except (TypeError, ValueError):
                    order = None
            if order is None and qr_id:
                order = Order.query.filter_by(upi_qr_id=qr_id).first()

            if order and order.status != 'Paid':
                order.status = 'Paid'
                order.payment_id = pay_entity.get('id') or order.payment_id or 'upi-qr'
                db.session.add(order)
                try:
                    db.session.add(OrderAudit(
                        order_id=order.order_id, admin_id=None, action='upi_qr_paid',
                        meta=json.dumps({'payment_id': order.payment_id, 'qr_id': qr_id})))
                except Exception:
                    pass
                db.session.commit()
        except Exception as exc:
            maybe_capture_exception(exc)
            db.session.rollback()
            return jsonify({'status': 'error'}), 200  # ack anyway; logged for retry-safety

    return jsonify({'status': 'ok'}), 200
