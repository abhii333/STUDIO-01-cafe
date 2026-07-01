#!/usr/bin/env bash
set -e
# Usage: ./scripts/optimize_images.sh [source_dir]
PY=".venv-1/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
${PY} scripts/image_optimize.py "$1"
