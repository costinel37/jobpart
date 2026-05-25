from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import logging
import os

from database import engine
import models
from routers import auth, jobs, applications, admin, upload, reviews, favorite, mesaje, notificari, export
from security import (
    limiter, SecurityHeadersMiddleware,
    RequestLoggingMiddleware, eroare_rate_limit
)

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

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")


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

@app.get("/{page}.html")
def pagina(page: str):
    file_path = os.path.join(frontend_path, f"{page}.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(frontend_path, "index.html"))
