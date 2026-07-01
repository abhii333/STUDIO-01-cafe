#!/usr/bin/env bash
set -e
URL=${1:-http://127.0.0.1:5000}

echo "Checking ${URL}/health"
curl -fsS ${URL}/health

echo "OK"
