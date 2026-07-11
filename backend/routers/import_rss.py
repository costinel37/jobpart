from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
import urllib.request
import xml.etree.ElementTree as ET
import re
import logging

from database import get_db, SessionLocal
import models
from auth import require_rol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import/rss", tags=["Import RSS"])


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
        logger.info(f"[RSS] Feed {feed_id}: {importate} joburi noi importate")

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


@router.post("")
def inregistreaza_feed(
    body: RssBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator")),
):
    if not body.url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL invalid.")

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


@router.get("")
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


@router.post("/sync")
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


@router.delete("")
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
