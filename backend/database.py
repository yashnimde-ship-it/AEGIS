import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Loads .env from cwd or nearest parent directory.
# No-op if DATABASE_URL is already set in the environment (e.g., App Runner).
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "For local dev, add it to a .env file. "
        "For production, set it as an App Runner environment variable."
    )

# pool_pre_ping=True reconnects after Neon's serverless idle/sleep cycles.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
