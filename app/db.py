from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database connection URL
DATABASE_URL = "postgresql+psycopg://plate_checker:plate_checker_db@db:5432/plate_checker_db"

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# FastAPI dependency: yields one DB session per request, always closed afterward

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()