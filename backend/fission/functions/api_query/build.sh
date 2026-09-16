#!/bin/sh
set -eu
python -m pip install -r "$SRC_PKG/requirements.txt" -t "$SRC_PKG"
mkdir -p "$DEPLOY_PKG"
cp -R "$SRC_PKG"/. "$DEPLOY_PKG"/
