#!/usr/bin/env bash
# build.sh — runs automatically on every Render deploy

set -o errexit  # exit immediately if any command fails

pip install -r requirements.txt

flask db upgrade
