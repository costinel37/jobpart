from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./joburi.db")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_schimba_urgent")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")

MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "noreply@jobpart.ro")
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_STARTTLS = os.getenv("MAIL_STARTTLS", "True") == "True"
MAIL_SSL_TLS = os.getenv("MAIL_SSL_TLS", "False") == "True"

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
