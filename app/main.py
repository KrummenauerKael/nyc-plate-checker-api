from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Plate, Violation, Lookup
import requests
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# Open Data uses many codes per borough; map known ones to one name
BOROUGHS = {
    "NY": "Manhattan", "MN": "Manhattan",
    "K": "Brooklyn", "BK": "Brooklyn", "KINGS": "Brooklyn",
    "Q": "Queens", "QN": "Queens", "QNS": "Queens", "QUEEN": "Queens",
    "BX": "Bronx", "BRONX": "Bronx",
    "R": "Staten Island", "ST": "Staten Island", "RICH": "Staten Island",
}


# Shared by both cache paths so the response shape can't drift
def format_violations(violations):
    violation_list = []
    for v in violations:
        rd = v.raw_data or {} # or {} guards against rows with no raw_data
        county = rd.get("county")
        violation_list.append({
            "summons_number": v.summons_number,
            "amount_due": v.amount_due,
            "total_amount": v.total_amount,
            "payment_amount": Decimal(rd.get("payment_amount", 0)),
            "fine_amount": Decimal(rd.get("fine_amount", 0)),
            "penalty_amount": Decimal(rd.get("penalty_amount", 0)),
            "interest_amount": Decimal(rd.get("interest_amount", 0)),
            "violation_date": v.violation_date,
            "violation_time": rd.get("violation_time"),
            "violation_type": rd.get("violation"),
            "violation_status": rd.get("violation_status"),
            "license_type": rd.get("license_type"),
            "county": BOROUGHS.get(county.upper(), county) if county else None,
        })
    return violation_list

app = FastAPI()

@app.get("/plates/{state}/{plate}")
def get_plate(state: str, plate: str, db: Session = Depends(get_db)):
    # Normalize so ny/abc and NY/ABC hit the same cache row
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
        # Newest first; undated tickets at the end
        violations = db.query(Violation).filter(Violation.plate_id == existing.id).order_by(Violation.violation_date.desc().nulls_last()).all()

        # Log the lookup (used for pruning)
        db.add(Lookup(plate_id=existing.id))
        db.commit()

        return {
            "state": state,
            "plate": plate,
            "source": "cache",
            "violation_count": len(violations),
            "violations": format_violations(violations)
        }

    # Cache miss or stale: fetch current data from NYC Open Data
    else:
        url = "https://data.cityofnewyork.us/resource/nc67-uf89.json"
        response = requests.get(url, params={"plate": plate, "state": state, "$limit": 50000}) # params escapes input; $limit raises Socrata's 1,000-row default
        response.raise_for_status() # Stop here if Open Data returned an error, don't treat it as data
        data = response.json()

        # Create the plate if new; flush so existing.id exists for the FKs below
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

            # No total field in Open Data; derive it
            violation.total_amount = Decimal(record.get("fine_amount", "0")) + Decimal(record.get("penalty_amount", "0")) + Decimal(record.get("interest_amount", "0"))
            violation.amount_due = record.get("amount_due")
            violation.raw_data = record # store entire record as JSONB
            issue_date = record.get("issue_date") # Some records have no issue_date; strptime(None) would crash

            if issue_date:
                violation.violation_date = datetime.strptime(issue_date, "%m/%d/%Y").date()

        # Log this query; saved by the commit below (after flush, so existing.id is set)
        db.add(Lookup(plate_id=existing.id))

        # Finalize the Plate,Violation, Lookup changes staged above
        db.commit()

        # Newest first; undated tickets at the end
        violations = db.query(Violation).filter(Violation.plate_id == existing.id).order_by(Violation.violation_date.desc().nulls_last()).all()
        return {
            "state": state,
            "plate": plate,
            "source": "open_data",
            "violation_count": len(violations),
            "violations": format_violations(violations)
        }


