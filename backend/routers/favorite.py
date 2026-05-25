from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas
from auth import get_user_curent

router = APIRouter(prefix="/api/favorite", tags=["Favorite"])


@router.post("/{job_id}")
def adauga_favorit(job_id: int, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    job = db.query(models.Job).filter(models.Job.id == job_id, models.Job.activ == True).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există.")
    existent = db.query(models.Favorite).filter_by(user_id=current_user.id, job_id=job_id).first()
    if existent:
        raise HTTPException(status_code=400, detail="Job deja salvat.")
    db.add(models.Favorite(user_id=current_user.id, job_id=job_id))
    db.commit()
    return {"mesaj": "Job salvat la favorite."}


@router.delete("/{job_id}")
def sterge_favorit(job_id: int, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    fav = db.query(models.Favorite).filter_by(user_id=current_user.id, job_id=job_id).first()
    if not fav:
        raise HTTPException(status_code=404, detail="Jobul nu e în favorite.")
    db.delete(fav)
    db.commit()
    return {"mesaj": "Job eliminat din favorite."}


@router.get("", response_model=List[schemas.JobOut])
def lista_favorite(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    favs = db.query(models.Favorite).filter_by(user_id=current_user.id).order_by(models.Favorite.creat_la.desc()).all()
    return [f.job for f in favs if f.job and f.job.activ]


@router.get("/ids")
def ids_favorite(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    favs = db.query(models.Favorite.job_id).filter_by(user_id=current_user.id).all()
    return {"ids": [f.job_id for f in favs]}
