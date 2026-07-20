from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import urllib.request
import urllib.parse
import ipaddress
import xml.etree.ElementTree as ET
import re
import logging

from database import get_db, SessionLocal
import models
from auth import require_rol
from security import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Import RSS / Parteneri"])

# ---------------------------------------------------------------------------
# Anti-fraud filter
# ---------------------------------------------------------------------------

_BLACKLIST = [
    "bitcoin", "crypto", "cryptocurrency", "nft", "ethereum", "litecoin",
    "forex", "trading binar", "binary options", "optiuni binare",
    "investitie garantata", "castig garantat", "profit garantat",
    "randament garantat", "venit garantat", "guaranteed income",
    "guaranteed profit", "guaranteed earnings",
    "mlm", "network marketing", "vanzari directe piramida",
    "schema ponzi", "ponzi scheme", "piramida financiara", "financial pyramid",
    "recrutezi membrii si castigi", "adaugi colegi si primesti",
    "escorta", "escort service", "adult entertainment", "onlyfans",
    "casino", "cazino", "pacanele", "jocuri de noroc", "pariuri sportive",
    "betting", "gambling",
    "castigi mii de euro acasa", "muncesti de acasa si castigi",
    "earn thousands from home", "make money fast", "get rich quick",
    "passive income guaranteed", "venit pasiv garantat",
    "forex robot", "trading automat garantat", "crypto mining",
    "work from home earn thousands",
]


def _verifica_frauda(titlu: str, descriere: str) -> tuple[bool, str]:
    text = (titlu + " " + (descriere or "")).lower()

    for kw in _BLACKLIST:
        if kw in text:
            return True, f"keyword suspect: '{kw}'"

    # Salary sanity — part-time >3000 EUR or >15000 RON is unrealistic
    for m in re.finditer(r"([\d][\d\s\.,]*)(?:euro|eur|€)", text, re.IGNORECASE):
        try:
            val = float(re.sub(r"[\s\.]", "", m.group(1)).replace(",", "."))
            if val > 3000:
                return True, f"salariu suspect ({m.group(0).strip()})"
        except ValueError:
            pass
    for m in re.finditer(r"([\d][\d\s\.,]*)(?:usd|\$)", text, re.IGNORECASE):
        try:
            val = float(re.sub(r"[\s\.]", "", m.group(1)).replace(",", "."))
            if val > 3000:
                return True, f"salariu suspect ({m.group(0).strip()})"
        except ValueError:
            pass
    for m in re.finditer(r"([\d][\d\s\.,]*)\s*ron", text, re.IGNORECASE):
        try:
            val = float(re.sub(r"[\s\.]", "", m.group(1)).replace(",", "."))
            if val > 15000:
                return True, f"salariu suspect ({m.group(0).strip()})"
        except ValueError:
            pass

    return False, ""


# ---------------------------------------------------------------------------
# SSRF protection — block private/internal IP ranges
# ---------------------------------------------------------------------------

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # AWS/GCP metadata
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _valideaza_url_rss(url: str) -> None:
    """Ridică HTTPException dacă URL-ul pointează spre o resursă internă (SSRF)."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL-ul trebuie să înceapă cu https://")
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        # Blochează localhost și variante
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise HTTPException(status_code=400, detail="URL intern nepermis.")
        # Blochează IP-uri private/rezervate
        try:
            addr = ipaddress.ip_address(host)
            if any(addr in net for net in _PRIVATE_NETS):
                raise HTTPException(status_code=400, detail="URL intern nepermis.")
        except ValueError:
            pass  # e hostname, nu IP — OK
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="URL RSS invalid.")


# ---------------------------------------------------------------------------
# RSS router
# ---------------------------------------------------------------------------

rss_router = APIRouter(prefix="/api/import/rss", tags=["Import RSS"])


class RssBody(BaseModel):
    url: str


def _strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:3000]


def sync_feed(feed_id: int):
    db: Session = SessionLocal()
    try:
        feed = db.query(models.RssFeed).filter(models.RssFeed.id == feed_id).first()
        if not feed or not feed.activ:
            return

        req = urllib.request.Request(
            feed.url, headers={"User-Agent": "JobPart RSS Bot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            xml_data = r.read()

        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []

        angajator = db.query(models.User).filter(
            models.User.id == feed.angajator_id
        ).first()
        companie = angajator.nume if angajator else "Angajator"

        importate = 0
        blocate = 0
        for item in items:
            def get(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            guid = get("guid") or get("link")
            if not guid:
                continue

            existent = db.query(models.Job).filter(
                models.Job.rss_guid == guid,
                models.Job.angajator_id == feed.angajator_id,
            ).first()
            if existent:
                continue

            titlu = get("title")
            if not titlu:
                continue

            descriere = _strip_html(get("description"))

            categorie = get("category") or None

            # Anti-fraud filter — save as inactive for admin review instead of dropping
            frauda, motiv = _verifica_frauda(titlu, descriere)
            if frauda:
                logger.warning(
                    f"[RSS][ANTI-FRAUDA] Feed {feed_id} — job pus in revizie: '{titlu[:60]}' ({motiv})"
                )
                job = models.Job(
                    titlu=titlu[:200],
                    descriere=descriere or titlu,
                    companie=companie,
                    oras=angajator.oras or "România",
                    tip_program="part-time",
                    categorie=categorie[:100] if categorie else None,
                    activ=False,
                    blocat_antifrauda=True,
                    motiv_blocare=motiv[:500],
                    expira_la=datetime.utcnow() + timedelta(days=365),
                    angajator_id=feed.angajator_id,
                    rss_guid=guid[:500],
                )
                db.add(job)
                blocate += 1
                continue

            job = models.Job(
                titlu=titlu[:200],
                descriere=descriere or titlu,
                companie=companie,
                oras=angajator.oras or "România",
                tip_program="part-time",
                categorie=categorie[:100] if categorie else None,
                activ=True,
                expira_la=datetime.utcnow() + timedelta(days=365),
                angajator_id=feed.angajator_id,
                rss_guid=guid[:500],
            )
            db.add(job)
            importate += 1

        db.commit()
        feed.ultima_sincronizare = datetime.utcnow()
        feed.joburi_importate = (feed.joburi_importate or 0) + importate
        feed.eroare = None
        db.commit()
        logger.info(f"[RSS] Feed {feed_id}: {importate} joburi importate, {blocate} blocate anti-frauda")

    except Exception as e:
        logger.warning(f"[RSS] Eroare feed {feed_id}: {e}")
        try:
            feed = db.query(models.RssFeed).filter(models.RssFeed.id == feed_id).first()
            if feed:
                feed.eroare = str(e)[:500]
                feed.ultima_sincronizare = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def sync_toate_feedurile():
    """Rulat periodic din expirare_jobs pentru sync automat."""
    db: Session = SessionLocal()
    try:
        feeduri = db.query(models.RssFeed).filter(models.RssFeed.activ == True).all()
        ids = [f.id for f in feeduri]
        logger.info(f"[RSS] Auto-sync: {len(ids)} feeduri")
    finally:
        db.close()

    for feed_id in ids:
        try:
            sync_feed(feed_id)
        except Exception as e:
            logger.warning(f"[RSS] Auto-sync eroare feed {feed_id}: {e}")


@rss_router.post("")
@limiter.limit("5/minute")
def inregistreaza_feed(
    request: Request,
    body: RssBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator")),
):
    _valideaza_url_rss(body.url)

    feed = db.query(models.RssFeed).filter(
        models.RssFeed.angajator_id == current_user.id
    ).first()
    if feed:
        feed.url = body.url
        feed.activ = True
        feed.eroare = None
    else:
        feed = models.RssFeed(angajator_id=current_user.id, url=body.url)
        db.add(feed)
    db.commit()
    db.refresh(feed)

    background_tasks.add_task(sync_feed, feed.id)
    return {"id": feed.id, "mesaj": "Feed înregistrat. Importul a început în fundal."}


@rss_router.get("")
def get_feed(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator")),
):
    feed = db.query(models.RssFeed).filter(
        models.RssFeed.angajator_id == current_user.id
    ).first()
    if not feed:
        return None
    return {
        "id": feed.id,
        "url": feed.url,
        "activ": feed.activ,
        "ultima_sincronizare": feed.ultima_sincronizare.isoformat() if feed.ultima_sincronizare else None,
        "joburi_importate": feed.joburi_importate or 0,
        "eroare": feed.eroare,
    }


@rss_router.post("/sync")
def sync_manual(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator")),
):
    feed = db.query(models.RssFeed).filter(
        models.RssFeed.angajator_id == current_user.id
    ).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Nu ai niciun feed RSS înregistrat.")
    background_tasks.add_task(sync_feed, feed.id)
    return {"mesaj": "Sincronizare pornită. Reîncarcă pagina în câteva secunde."}


@rss_router.delete("")
def sterge_feed(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator")),
):
    feed = db.query(models.RssFeed).filter(
        models.RssFeed.angajator_id == current_user.id
    ).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Nu ai niciun feed RSS.")
    db.delete(feed)
    db.commit()
    return {"mesaj": "Feed RSS șters."}


# ---------------------------------------------------------------------------
# Partner application router
# ---------------------------------------------------------------------------

parteneri_router = APIRouter(prefix="/api/parteneri", tags=["Parteneri"])


class PartenerBody(BaseModel):
    nume_companie: str
    website: str
    email: str
    url_rss: Optional[str] = None
    tara: Optional[str] = None
    cui: Optional[str] = None
    descriere: Optional[str] = None


@parteneri_router.post("/aplicatie")
@limiter.limit("5/hour")
def trimite_aplicatie_partener(request: Request, body: PartenerBody, db: Session = Depends(get_db)):
    if not body.nume_companie.strip() or not body.email.strip() or not body.website.strip():
        raise HTTPException(status_code=400, detail="Câmpurile obligatorii lipsesc.")

    # Basic website format check
    if not body.website.startswith("http"):
        raise HTTPException(status_code=400, detail="Website-ul trebuie să înceapă cu https://")

    aplicatie = models.PartenerAplicatie(
        nume_companie=body.nume_companie[:200],
        website=body.website[:500],
        email=body.email[:200],
        url_rss=body.url_rss[:500] if body.url_rss else None,
        tara=body.tara,
        cui=body.cui[:30] if body.cui else None,
        descriere=body.descriere[:2000] if body.descriere else None,
    )
    db.add(aplicatie)
    db.commit()
    logger.info(f"[PARTENER] Aplicatie noua: {body.nume_companie} <{body.email}>")
    return {
        "mesaj": "Aplicație primită! Te vom contacta la adresa de email în 24-48h după verificare."
    }


# ---------------------------------------------------------------------------
# Combined router exported to main.py
# ---------------------------------------------------------------------------

from fastapi import APIRouter as _AR
router = _AR()
router.include_router(rss_router)
router.include_router(parteneri_router)
