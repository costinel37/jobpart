from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text, inspect
from datetime import datetime
import logging
import os

from database import engine
import models
from routers import auth, jobs, applications, admin, upload, reviews, favorite, mesaje, notificari, export, promotii, precontracte, alerts
from security import (
    limiter, SecurityHeadersMiddleware,
    RequestLoggingMiddleware, eroare_rate_limit
)
from expirare_jobs import porneste_task_expirare, porneste_keep_alive, porneste_monitorizare
from auth import hash_parola
from database import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

models.Base.metadata.create_all(bind=engine)

ENV = os.getenv("ENVIRONMENT", "development")

ALLOWED_ORIGINS = (
    ["*"] if ENV == "development"
    else [
        os.getenv("FRONTEND_URL", "https://jobpart.ro"),
        "https://www.jobpart.ro",
    ]
)

app = FastAPI(
    title="JobPart API",
    version="2.0.0",
    docs_url="/docs" if ENV == "development" else None,
    redoc_url=None,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, eroare_rate_limit)

# Compresie GZip
app.add_middleware(GZipMiddleware, minimum_size=500)

# Middleware (ordinea contează: primul adăugat = ultimul executat)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(admin.router)
app.include_router(upload.router)
app.include_router(reviews.router)
app.include_router(favorite.router)
app.include_router(mesaje.router)
app.include_router(notificari.router)
app.include_router(export.router)
app.include_router(promotii.router)
app.include_router(precontracte.router)
app.include_router(alerts.router)

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.on_event("startup")
def startup():
    # Migrare automata coloane noi — compatibil SQLite si PostgreSQL
    coloane_noi = {
        "users": [
            ("newsletter_consimtit", "BOOLEAN DEFAULT FALSE"),
            ("gdpr_consimtit_la", "DATETIME"),
            ("data_nasterii", "DATE"),
            ("parola_schimbata_la", "DATETIME"),
            ("email_confirmat", "BOOLEAN DEFAULT FALSE"),
            ("cv_profil_path", "VARCHAR(500)"),
            ("cv_profil_nume", "VARCHAR(255)"),
        ],
        "jobs": [
            ("avertisment_expirare", "BOOLEAN DEFAULT FALSE"),
            ("promovat", "BOOLEAN DEFAULT FALSE"),
            ("promovat_pana", "DATETIME"),
        ],
    }
    insp = inspect(engine)
    with engine.connect() as conn:
        for tabel, coloane in coloane_noi.items():
            try:
                existente = {col["name"] for col in insp.get_columns(tabel)}
            except Exception:
                existente = set()
            for coloana, definitie in coloane:
                if coloana not in existente:
                    try:
                        conn.execute(text(f"ALTER TABLE {tabel} ADD COLUMN {coloana} {definitie}"))
                        conn.commit()
                        logging.info(f"Migrare: coloana '{coloana}' adaugata in '{tabel}'.")
                    except Exception as e:
                        logging.warning(f"Migrare '{coloana}' in '{tabel}': {e}")
    # Sincronizeaza contul admin — nu reseta parola daca exista deja
    db = SessionLocal()
    try:
        admin = db.query(models.User).filter(
            models.User.email == "admin@jobpart.ro"
        ).first()
        if not admin:
            admin_pass = os.getenv("ADMIN_PASSWORD")
            if not admin_pass:
                import secrets
                admin_pass = secrets.token_urlsafe(16)
                logging.warning(f"[STARTUP] ADMIN_PASSWORD negăsit — parolă generată automat: {admin_pass} — schimb-o imediat!")
            db.add(models.User(
                nume="Administrator",
                email="admin@jobpart.ro",
                parola_hash=hash_parola(admin_pass),
                rol="admin",
                activ=True,
                email_confirmat=True,
                gdpr_consimtit_la=datetime.utcnow(),
            ))
            logging.info("Admin creat: admin@jobpart.ro")
        else:
            admin.rol = "admin"
            admin.activ = True
        db.commit()
    except Exception as e:
        logging.warning(f"Sync admin: {e}")
    finally:
        db.close()
    porneste_task_expirare(interval_secunde=300)
    porneste_keep_alive(interval_secunde=600)
    porneste_monitorizare(interval_secunde=86400)


@app.exception_handler(500)
async def eroare_server(request: Request, exc: Exception):
    logging.error(f"Eroare internă: {exc} | {request.url}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Eroare internă de server. Contactează administratorul."}
    )




@app.get("/")
def root():
    return FileResponse(os.path.join(frontend_path, "index.html"))

@app.get("/ping")
def ping():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return """User-agent: *
Disallow: /static/admin.html
Disallow: /static/dashboard-candidat.html
Disallow: /static/dashboard-angajator.html
Disallow: /static/mesaje.html
Disallow: /static/notificari.html
Disallow: /static/precontract.html
Disallow: /static/favorite.html
Disallow: /static/profil.html
Disallow: /static/resetare-parola.html
Disallow: /static/confirmare-email.html
Disallow: /static/plata-succes.html
Disallow: /api/
Sitemap: https://jobpart.ro/sitemap.xml
"""


@app.get("/sitemap.xml", response_class=PlainTextResponse)
def sitemap(db=None):
    from database import SessionLocal
    db = SessionLocal()
    try:
        joburi = db.query(models.Job).filter(models.Job.activ == True).all()
        urls = [
            "<url><loc>https://jobpart.ro/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
            "<url><loc>https://jobpart.ro/static/jobs.html</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>",
            "<url><loc>https://jobpart.ro/static/harta.html</loc><changefreq>daily</changefreq><priority>0.7</priority></url>",
            "<url><loc>https://jobpart.ro/static/register.html</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>",
            "<url><loc>https://jobpart.ro/static/termeni.html</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>",
            "<url><loc>https://jobpart.ro/static/confidentialitate.html</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>",
        ]
        for job in joburi:
            urls.append(
                f"<url><loc>https://jobpart.ro/static/job-detalii.html?id={job.id}</loc>"
                f"<lastmod>{job.creat_la.strftime('%Y-%m-%d')}</lastmod>"
                f"<changefreq>weekly</changefreq><priority>0.8</priority></url>"
            )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(urls)}
</urlset>"""
    finally:
        db.close()


@app.get("/{page}.html")
def pagina(page: str):
    file_path = os.path.join(frontend_path, f"{page}.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(frontend_path, "index.html"))
