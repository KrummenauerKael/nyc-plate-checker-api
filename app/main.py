from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Plate, Violation
import requests
from datetime import datetime, timezone, timedelta

app = FastAPI()

@app.get("/plates/{state}/{plate}")
def get_plate(state: str, plate: str, db: Session = Depends(get_db)):
    existing = db.query(Plate).filter(Plate.plate == plate, Plate.state == state).first()

    # 24h TTL matches Open Data's own daily refresh cadence
    TTL_HOURS = 24

    # True only if we have a row, it's been fetched at least once, and it's within the TTL window
    is_fresh = (
        existing is not None
        and existing.fetched_at is not None
        and (datetime.now(timezone.utc) - existing.fetched_at < timedelta(hours=TTL_HOURS))
    )

    # Cache hit: serve stored violations without calling Open Data
    if is_fresh:
        violations = db.query(Violation).filter(Violation.plate_id == existing.id).all()
        return {
            "state": state,
            "plate": plate,
            "source": "cache",
            "violation_count": len(violations),
        }

    # Cache miss or stale: fetch current data from NYC Open Data
    else:
        url = f"https://data.cityofnewyork.us/resource/nc67-uf89.json?plate={plate}&state={state}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        if existing is None:
            existing = Plate(plate=plate, state=state)
            db.add(existing)
        existing.fetched_at = datetime.now(timezone.utc)
        db.flush()

        # Upsert: update the violation if we've seen this summons before, else insert a new one
        for record in data:
            summons = record.get("summons_number")
            violations = db.query(Violation).filter(Violation.summons_number == summons).first()
            if violations is None:
                violation = Violation(summons_number=summons, plate_id=existing.id)
                db.add(violation)
            violation.amount_due = record.get("amount_due")
            
        # Finalize the Plate + Violation changes staged above
        db.commit()

        violations = db.query(Violation).filter(Violation.plate_id == existing.id).all()
        return {
            "state": state,
            "plate": plate,
            "source": "open_data",
            "violation_count": len(violations),
        }


