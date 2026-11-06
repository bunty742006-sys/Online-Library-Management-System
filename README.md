# Online Library Management System

Flask + SQLite app for managing books, students and loans.

## Run locally
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python app.py            # http://localhost:5000

Default login: `admin` / `admin123` (override with ADMIN_USERNAME / ADMIN_PASSWORD).

## Tests
    pytest tests

## Docker
    docker compose up --build

Set `SECRET_KEY` and `ADMIN_PASSWORD` before deploying anywhere real.
