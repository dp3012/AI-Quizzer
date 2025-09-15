#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Running migrations..."
# python manage.py makemigrations
python manage.py migrate

echo "Starting server..."
uvicorn api.main:app --host 0.0.0.0 --port 8000