from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from database import get_db
import models, schemas
from auth import get_user_curent
from security import limiter

router = APIRouter(prefix="/api/recenzii", tags=["Recenzii"])


@router.post("", response_model=schemas.ReviewOut)
@limiter.limit("5/minute")
def scrie_recenzie(
    request: Request,
    data: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating-ul trebuie să fie între 1 și 5.")

    if data.subiect_id == current_user.id:
        raise HTTPException(status_code=400, detail="Nu poți lăsa o recenzie pentru tine însuți.")

    subiect = db.query(models.User).filter(models.User.id == data.subiect_id, models.User.activ == True).first()
    if not subiect:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")

    existent = db.query(models.Review).filter(
        models.Review.autor_id == current_user.id,
        models.Review.subiect_id == data.subiect_id,
    ).first()
    if existent:
        raise HTTPException(status_code=400, detail="Ai lăsat deja o recenzie pentru acest utilizator.")

    review = models.Review(
        autor_id=current_user.id,
        subiect_id=data.subiect_id,
        rating=data.rating,
        comentariu=data.comentariu,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    out = schemas.ReviewOut.model_validate(review)
    out.autor_nume = current_user.nume
    return out


@router.get("/utilizator/{user_id}", response_model=List[schemas.ReviewOut])
def recenzii_utilizator(user_id: int, db: Session = Depends(get_db)):
    reviews = db.query(models.Review).filter(
        models.Review.subiect_id == user_id
    ).order_by(models.Review.creat_la.desc()).all()

    rezultate = []
    for r in reviews:
        out = schemas.ReviewOut.model_validate(r)
        out.autor_nume = r.autor.nume if r.autor else "Anonim"
        rezultate.append(out)
    return rezultate


@router.get("/utilizator/{user_id}/medie", response_model=schemas.RatingMedie)
def rating_mediu(user_id: int, db: Session = Depends(get_db)):
    rezultat = db.query(
        func.avg(models.Review.rating).label("medie"),
        func.count(models.Review.id).label("total"),
    ).filter(models.Review.subiect_id == user_id).first()

    return {
        "medie": round(float(rezultat.medie or 0), 1),
        "total": rezultat.total or 0,
    }


@router.delete("/{review_id}")
def sterge_recenzie(
    review_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Recenzia nu există.")
    if review.autor_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu poți șterge această recenzie.")
    db.delete(review)
    db.commit()
    return {"mesaj": "Recenzie ștearsă."}
