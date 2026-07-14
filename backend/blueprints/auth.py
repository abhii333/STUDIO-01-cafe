"""Authentication blueprint: register, login, refresh, password reset/change."""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, create_access_token
from werkzeug.security import check_password_hash

from models import db, User, ReferralCode
from extensions import limiter
from helpers import hash_password, issue_tokens, user_public, current_user_id

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    ref_code = (data.get('referral_code') or '').strip()

    if not username or not email or not password:
        return jsonify({'success': False, 'message': 'Username, email, and password are required.'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': 'Username taken.'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered.'}), 409

    new_user = User(username=username, email=email, password=hash_password(password))
    db.session.add(new_user)
    db.session.flush()

    if ref_code:
        ref = ReferralCode.query.filter(db.func.lower(ReferralCode.code) == ref_code.lower()).first()
        if ref and ref.owner_id != new_user.id:
            owner = User.query.get(ref.owner_id)
            if owner:
                owner.coins += 50
            new_user.coins += 50

    # Referral code mirrors the username as typed (capped to the column length).
    db.session.add(ReferralCode(code=username[:10], owner_id=new_user.id))
    db.session.commit()

    access, refresh = issue_tokens(new_user)
    return jsonify({'success': True, 'access_token': access, 'refresh_token': refresh,
                    'user': user_public(new_user)}), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(username=(data.get('username') or '').strip()).first()
    if user and check_password_hash(user.password, data.get('password') or ''):
        access, refresh = issue_tokens(user)
        return jsonify({'success': True, 'access_token': access, 'refresh_token': refresh,
                        'user': user_public(user)})
    return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401


@auth_bp.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    uid = current_user_id()
    user = User.query.get(uid)
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404
    access = create_access_token(identity=str(user.id),
                                 additional_claims={'role': user.role, 'username': user.username})
    return jsonify({'success': True, 'access_token': access})


@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
@limiter.limit("5 per minute")
def forgot_password():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=(data.get('email') or '').strip()).first()
    if user:
        token = secrets.token_urlsafe(16)
        user.reset_token = token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        print(f"\n[RESET TOKEN FOR {user.username}]: {token}\n")
    # Generic response either way (do not reveal whether the email exists)
    return jsonify({'success': True,
                    'message': 'If an account exists, a reset token has been issued.'})


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
@limiter.limit("5 per minute")
def reset_password():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    password = data.get('password') or ''
    if not token or not password:
        return jsonify({'success': False, 'message': 'Token and password required.'}), 400
    user = User.query.filter_by(reset_token=token).first()
    if not user:
        return jsonify({'success': False, 'message': 'Invalid or expired token.'}), 400
    # Tokens issued before this feature existed have no expiry set — treat as
    # expired so they must request a fresh one, rather than trusting them forever.
    if not user.reset_token_expires or datetime.utcnow() > user.reset_token_expires:
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()
        return jsonify({'success': False, 'message': 'Invalid or expired token.'}), 400
    user.password = hash_password(password)
    user.reset_token = None
    user.reset_token_expires = None
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password reset successfully.'})


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@jwt_required()
def change_password():
    data = request.get_json(silent=True) or {}
    user = User.query.get(current_user_id())
    if not user or not check_password_hash(user.password, data.get('current_password') or ''):
        return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 400
    new_password = data.get('new_password') or ''
    if len(new_password) < 4:
        return jsonify({'success': False, 'message': 'New password is too short.'}), 400
    user.password = hash_password(new_password)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password changed successfully.'})
