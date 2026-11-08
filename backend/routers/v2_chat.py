"""
Chat în timp real angajator ↔ candidat — /api/v2/chat

O conversație = o aplicare. Pot scrie doar cele două părți: candidatul care a aplicat
și angajatorul care a publicat jobul. Fără aplicare nu există conversație (anti-spam).

Transport:
  WebSocket  /api/v2/chat/ws      — timp real (mesaje, „scrie…”, confirmări de citire)
  REST       /api/v2/chat/...     — istoric + rezervă când WebSocket-ul nu e disponibil

Autentificare WebSocket: primul mesaj trimis de client e {"type":"auth","token":"..."}.
(Nu punem tokenul în URL, ca să nu apară în log-urile serverului.)

Notă de scalare: conexiunile sunt ținute în memorie → funcționează pe o singură instanță
(cazul actual pe Render). Pentru mai multe instanțe se adaugă Redis pub/sub.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import models_v2 as m2
from auth import get_user_curent
from database import SessionLocal, get_db
from notificari_service import creeaza_notificare

router = APIRouter(prefix="/api/v2/chat", tags=["v2 Chat"])
log = logging.getLogger("chat")

MAX_BODY = 2000
RATE_WINDOW_S, RATE_MAX = 10, 12           # max 12 mesaje / 10 secunde / utilizator
NOTIFY_COOLDOWN = timedelta(minutes=10)     # o singură notificare per conversație la 10 min
CHAT_PAGE = "/static/chat.html"


# ─────────────────────────── conexiuni live ───────────────────────────

class Hub:
    def __init__(self):
        self.conns: dict[int, set[WebSocket]] = defaultdict(set)
        self.sent: dict[int, deque] = defaultdict(deque)

    def online(self, user_id: int) -> bool:
        return bool(self.conns.get(user_id))

    def add(self, user_id: int, ws: WebSocket):
        self.conns[user_id].add(ws)

    def remove(self, user_id: int, ws: WebSocket):
        self.conns[user_id].discard(ws)
        if not self.conns[user_id]:
            self.conns.pop(user_id, None)

    def allow(self, user_id: int) -> bool:
        now, q = time.monotonic(), self.sent[user_id]
        while q and now - q[0] > RATE_WINDOW_S:
            q.popleft()
        if len(q) >= RATE_MAX:
            return False
        q.append(now)
        return True

    async def send(self, user_ids, payload: dict):
        data = json.dumps(payload, default=str, ensure_ascii=False)
        for uid in set(user_ids):
            for ws in list(self.conns.get(uid, ())):
                try:
                    await ws.send_text(data)
                except Exception:
                    self.remove(uid, ws)


hub = Hub()


def _push_from_thread(user_ids, payload: dict):
    """Trimite live dintr-un endpoint sincron (rulat în threadpool)."""
    try:
        from_thread.run(hub.send, user_ids, payload)
    except Exception as e:  # fără event loop (ex. teste) — clientul va prelua prin REST
        log.debug("push skip: %s", e)


# ─────────────────────────── helpers ───────────────────────────

class Thread:
    def __init__(self, app: models.Application, job: models.Job, me: models.User):
        self.app, self.job, self.me = app, job, me
        self.employer_id = job.angajator_id
        self.candidate_id = app.candidat_id
        self.role = "employer" if me.id == self.employer_id else "candidate"
        self.other_id = self.candidate_id if self.role == "employer" else self.employer_id

    @property
    def participants(self):
        return (self.employer_id, self.candidate_id)


def _thread(db: Session, app_id: int, me: models.User) -> Thread:
    app = db.get(models.Application, app_id)
    job = app.job if app else None
    if not app or not job or me.id not in (app.candidat_id, job.angajator_id):
        raise HTTPException(404, "Conversația nu există.")
    return Thread(app, job, me)


def _out(msg: m2.ChatMessage) -> dict:
    return {
        "id": msg.id, "app_id": msg.application_id, "sender_id": msg.sender_id,
        "kind": msg.kind, "body": msg.body,
        "meta": json.loads(msg.meta) if msg.meta else None,
        "created_at": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "read_at": msg.read_at.replace(tzinfo=timezone.utc).isoformat() if msg.read_at else None,
    }


def _clean(text: str) -> str:
    text = (text or "").replace("\x00", "").strip()
    if not text:
        raise HTTPException(422, "Mesajul e gol.")
    return text[:MAX_BODY]


def _notify_offline(db: Session, t: Thread, preview: str):
    """Notificare în aplicație pentru destinatarul care nu e online (cu limitare)."""
    if hub.online(t.other_id):
        return
    link = f"{CHAT_PAGE}?app={t.app.id}"
    recent = db.query(models.Notification).filter(
        models.Notification.user_id == t.other_id,
        models.Notification.link == link,
        models.Notification.creat_la > datetime.utcnow() - NOTIFY_COOLDOWN,
    ).first()
    if recent:
        return
    who = t.job.companie if t.role == "employer" else (t.me.nume or "Candidat")
    creeaza_notificare(db, t.other_id, "chat_nou", f"💬 {who} ({t.job.titlu[:40]}): {preview[:80]}", link)


def _store(db: Session, t: Thread, kind: str, body: str, meta: Optional[dict] = None) -> dict:
    msg = m2.ChatMessage(application_id=t.app.id, sender_id=t.me.id, kind=kind,
                         body=body, meta=json.dumps(meta, ensure_ascii=False) if meta else None)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    _notify_offline(db, t, body)
    return _out(msg)


def _mark_read(db: Session, t: Thread) -> int:
    n = db.query(m2.ChatMessage).filter(
        m2.ChatMessage.application_id == t.app.id,
        m2.ChatMessage.sender_id != t.me.id,
        m2.ChatMessage.read_at.is_(None),
    ).update({"read_at": datetime.utcnow()}, synchronize_session=False)
    db.commit()
    return n


def _set_status(db: Session, t: Thread, status: str, motiv: Optional[str] = None):
    """Aceeași logică ca PUT /api/aplicari/{id}/status (email + notificare)."""
    if t.app.status == status:
        return
    t.app.status = status
    db.commit()
    candidat = db.get(models.User, t.candidate_id)
    if candidat and candidat.activ:
        from email_service import email_status_schimbat
        from routers.applications import _email_async
        _email_async(email_status_schimbat, candidat.email, t.job.titlu, t.job.companie, status, motiv)


# ─────────────────────────── REST ───────────────────────────

@router.get("/threads")
def list_threads(user=Depends(get_user_curent), db: Session = Depends(get_db)):
    q = db.query(models.Application, models.Job).join(models.Job, models.Job.id == models.Application.job_id)
    if user.rol == "candidat":
        q = q.filter(models.Application.candidat_id == user.id)
    else:
        q = q.filter(models.Job.angajator_id == user.id)
    rows = q.all()
    if not rows:
        return []
    ids = [a.id for a, _ in rows]

    last_ids = dict(db.query(m2.ChatMessage.application_id, func.max(m2.ChatMessage.id))
                    .filter(m2.ChatMessage.application_id.in_(ids)).group_by(m2.ChatMessage.application_id).all())
    last = {m.application_id: m for m in db.query(m2.ChatMessage).filter(m2.ChatMessage.id.in_(last_ids.values())).all()} if last_ids else {}
    unread = dict(db.query(m2.ChatMessage.application_id, func.count(m2.ChatMessage.id)).filter(
        m2.ChatMessage.application_id.in_(ids), m2.ChatMessage.sender_id != user.id, m2.ChatMessage.read_at.is_(None),
    ).group_by(m2.ChatMessage.application_id).all())
    people = {u.id: u for u in db.query(models.User).filter(
        models.User.id.in_({a.candidat_id for a, _ in rows} | {j.angajator_id for _, j in rows})).all()}

    out = []
    for app, job in rows:
        is_emp = user.id == job.angajator_id
        other = people.get(app.candidat_id if is_emp else job.angajator_id)
        lm = last.get(app.id)
        out.append({
            "app_id": app.id, "job_id": job.id, "job_title": job.titlu, "company": job.companie,
            "status": app.status, "role": "employer" if is_emp else "candidate",
            "other": {"id": other.id if other else None,
                      "name": (other.nume if other and other.activ else "Utilizator șters") if is_emp else job.companie,
                      "online": bool(other and hub.online(other.id))},
            "last": _out(lm) if lm else None,
            "unread": unread.get(app.id, 0),
            "sort": (lm.created_at if lm else app.creat_la or datetime.min).isoformat(),
        })
    out.sort(key=lambda x: x["sort"], reverse=True)
    return out


@router.get("/threads/{app_id}/messages")
def history(app_id: int, before_id: Optional[int] = Query(None, ge=1), limit: int = Query(50, ge=1, le=100),
            user=Depends(get_user_curent), db: Session = Depends(get_db)):
    t = _thread(db, app_id, user)
    q = db.query(m2.ChatMessage).filter(m2.ChatMessage.application_id == app_id)
    if before_id:
        q = q.filter(m2.ChatMessage.id < before_id)
    msgs = q.order_by(m2.ChatMessage.id.desc()).limit(limit).all()
    if _mark_read(db, t):
        _push_from_thread([t.other_id], {"type": "read", "app_id": app_id, "by": user.id})
    return {"messages": [_out(m) for m in reversed(msgs)], "has_more": len(msgs) == limit,
            "role": t.role, "status": t.app.status, "me": user.id}


class SendIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)


@router.post("/threads/{app_id}/messages")
def send(app_id: int, data: SendIn, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    if not hub.allow(user.id):
        raise HTTPException(429, "Prea multe mesaje. Așteaptă câteva secunde.")
    t = _thread(db, app_id, user)
    msg = _store(db, t, "text", _clean(data.body))
    _push_from_thread(t.participants, {"type": "message", "message": msg})
    return msg


class ActionIn(BaseModel):
    action: Literal["accept", "reject", "interview", "interview_yes", "interview_no"]
    reason: Optional[str] = Field(None, max_length=300)
    when: Optional[datetime] = None                      # ISO, cu fus orar
    mode: Optional[Literal["online", "onsite"]] = None
    where: Optional[str] = Field(None, max_length=300)   # adresă sau link de video-call
    ref: Optional[int] = None                            # id-ul propunerii de interviu


def _do_action(db: Session, t: Thread, a: ActionIn) -> dict:
    if a.action in ("accept", "reject", "interview") and t.role != "employer":
        raise HTTPException(403, "Doar angajatorul poate face această acțiune.")
    if a.action in ("interview_yes", "interview_no") and t.role != "candidate":
        raise HTTPException(403, "Doar candidatul poate răspunde la invitație.")

    if a.action == "accept":
        _set_status(db, t, "acceptata")
        return _store(db, t, "accept", "✅ Aplicarea ta a fost acceptată! Hai să stabilim detaliile.")
    if a.action == "reject":
        reason = (a.reason or "").strip()[:300] or None
        _set_status(db, t, "respinsa", reason)
        return _store(db, t, "reject", "Mulțumim pentru interes. De data aceasta am ales alt candidat."
                      + (f" Motiv: {reason}" if reason else ""))
    if a.action == "interview":
        if not a.when or not a.mode:
            raise HTTPException(422, "Alege data, ora și tipul interviului.")
        when = a.when if a.when.tzinfo else a.when.replace(tzinfo=timezone.utc)
        if when < datetime.now(timezone.utc):
            raise HTTPException(422, "Data interviului e în trecut.")
        if t.app.status == "trimisa":
            _set_status(db, t, "vizualizata")
        where = (a.where or "").strip()[:300]
        return _store(db, t, "interview", "📅 Invitație la interviu",
                      {"when": when.astimezone(timezone.utc).isoformat(), "mode": a.mode, "where": where})
    # răspunsul candidatului
    prop = db.get(m2.ChatMessage, a.ref) if a.ref else None
    if not prop or prop.application_id != t.app.id or prop.kind != "interview":
        raise HTTPException(404, "Invitația nu există.")
    yes = a.action == "interview_yes"
    return _store(db, t, a.action, "👍 Confirm interviul." if yes else "🙏 Nu pot la ora propusă. Putem alege altă dată?",
                  {"ref": prop.id})


@router.post("/threads/{app_id}/actions")
def action(app_id: int, data: ActionIn, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    t = _thread(db, app_id, user)
    msg = _do_action(db, t, data)
    _push_from_thread(t.participants, {"type": "message", "message": msg, "status": t.app.status})
    return {"message": msg, "status": t.app.status}


@router.post("/threads/{app_id}/read")
def mark_read(app_id: int, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    t = _thread(db, app_id, user)
    if _mark_read(db, t):
        _push_from_thread([t.other_id], {"type": "read", "app_id": app_id, "by": user.id})
    return {"ok": True}


@router.get("/unread")
def unread_total(user=Depends(get_user_curent), db: Session = Depends(get_db)):
    n = db.query(func.count(m2.ChatMessage.id)).join(
        models.Application, models.Application.id == m2.ChatMessage.application_id
    ).join(models.Job, models.Job.id == models.Application.job_id).filter(
        m2.ChatMessage.sender_id != user.id, m2.ChatMessage.read_at.is_(None),
        (models.Application.candidat_id == user.id) | (models.Job.angajator_id == user.id),
    ).scalar()
    return {"unread": n or 0}


# ─────────────────────────── WebSocket ───────────────────────────

def _ws_auth(token: str) -> Optional[int]:
    db = SessionLocal()
    try:
        return get_user_curent(token, db).id
    except Exception:
        return None
    finally:
        db.close()


def _ws_call(user_id: int, fn, *args):
    """Rulează o operație DB pentru utilizatorul conectat, cu sesiune proprie."""
    db = SessionLocal()
    try:
        me = db.get(models.User, user_id)
        if not me or not me.activ:
            raise HTTPException(401, "Sesiune invalidă.")
        return fn(db, me, *args)
    finally:
        db.close()


def _ws_send(db, me, app_id, body):
    t = _thread(db, app_id, me)
    return t.participants, _store(db, t, "text", _clean(body))


def _ws_peer(db, me, app_id):
    return _thread(db, app_id, me).other_id


def _ws_read(db, me, app_id):
    t = _thread(db, app_id, me)
    return t.other_id, _mark_read(db, t)


@router.websocket("/ws")
async def chat_ws(ws: WebSocket):
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
    except Exception:
        await ws.close(code=4401)
        return
    user_id = await run_in_threadpool(_ws_auth, str(first.get("token") or "")) if first.get("type") == "auth" else None
    if not user_id:
        await ws.close(code=4401)
        return

    hub.add(user_id, ws)
    await ws.send_text(json.dumps({"type": "ready", "me": user_id}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                ev = json.loads(raw)
                kind, app_id = ev.get("type"), int(ev.get("app_id") or 0)
            except Exception:
                continue
            try:
                if kind == "ping":
                    await ws.send_text('{"type":"pong"}')
                elif kind == "send":
                    if not hub.allow(user_id):
                        await ws.send_text(json.dumps({"type": "error", "client_id": ev.get("client_id"),
                                                       "detail": "Prea multe mesaje. Așteaptă câteva secunde."}))
                        continue
                    who, msg = await run_in_threadpool(_ws_call, user_id, _ws_send, app_id, str(ev.get("body") or ""))
                    msg["client_id"] = ev.get("client_id")
                    await hub.send(who, {"type": "message", "message": msg})
                elif kind == "typing":
                    peer = await run_in_threadpool(_ws_call, user_id, _ws_peer, app_id)
                    await hub.send([peer], {"type": "typing", "app_id": app_id, "from": user_id})
                elif kind == "read":
                    peer, n = await run_in_threadpool(_ws_call, user_id, _ws_read, app_id)
                    if n:
                        await hub.send([peer], {"type": "read", "app_id": app_id, "by": user_id})
            except HTTPException as e:
                await ws.send_text(json.dumps({"type": "error", "client_id": ev.get("client_id"), "detail": e.detail}))
                if e.status_code == 401:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws error: %s", e)
    finally:
        hub.remove(user_id, ws)
