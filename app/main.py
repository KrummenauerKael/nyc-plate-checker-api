from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Plate, Violation, Lookup
import requests
from datetime import datetime, timezone, timedelta

app = FastAPI()

@app.get("/plates/{state}/{plate}")
def get_plate(state: str, plate: str, db: Session = Depends(get_db)):
    state = state.upper()
    plate = plate.upper()
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

        # Log the lookup (used for pruning)
        db.add(Lookup(plate_id=existing.id))
        db.commit()
        return {
            "state": state,
            "plate": plate,
            "source": "cache",
            "violation_count": len(violations),
        }

    # Cache miss or stale: fetch current data from NYC Open Data
    else:
        url = "https://data.cityofnewyork.us/resource/nc67-uf89.json"
        response = requests.get(url, params={"plate": plate, "state": state, "$limit": 50000})
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
            violation = db.query(Violation).filter(Violation.summons_number == summons).first()
            if violation is None:
                violation = Violation(summons_number=summons, plate_id=existing.id)
                db.add(violation)
            violation.amount_due = record.get("amount_due")

        # Log this query; saved by the commit below (after flush, so existing.id is set)
        db.add(Lookup(plate_id=existing.id))

        # Finalize the Plate,Violation, Lookup changes staged above
        db.commit()

        violations = db.query(Violation).filter(Violation.plate_id == existing.id).all()
        return {
            "state": state,
            "plate": plate,
            "source": "open_data",
            "violation_count": len(violations),
        }


