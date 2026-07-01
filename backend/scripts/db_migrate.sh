#!/usr/bin/env bash
set -e
# Helper for running Flask-Migrate commands inside the venv
# Usage: ./scripts/db_migrate.sh init|migrate|upgrade
CMD=${1:-help}
. .venv-1/bin/activate
export FLASK_APP=app.py
case "$CMD" in
  init)
    flask db init || true
    ;;
  migrate)
    flask db migrate -m "$2"
    ;;
  upgrade)
    flask db upgrade
    ;;
  *)
    echo "Usage: $0 {init|migrate|upgrade} [message]"
    exit 1
    ;;
esac
