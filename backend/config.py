from dotenv import load_dotenv
import os
import sys

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./joburi.db")
# Railway livreaza postgres:// dar SQLAlchemy 2.0 necesita postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")

_SECRET_KEY = os.getenv("SECRET_KEY", "")
_ENV = os.getenv("ENVIRONMENT", "development")

if not _SECRET_KEY:
    if _ENV == "production":
        print("EROARE FATALĂ: SECRET_KEY nu este setat în .env! Aplicația nu poate porni în producție.", file=sys.stderr)
        sys.exit(1)
    else:
        _SECRET_KEY = "fallback_secret_doar_pentru_development_schimba_urgent"

SECRET_KEY = _SECRET_KEY

MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "noreply@jobpart.ro")
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_STARTTLS = os.getenv("MAIL_STARTTLS", "True") == "True"
MAIL_SSL_TLS = os.getenv("MAIL_SSL_TLS", "False") == "True"

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
