from sqlalchemy import text

from app.db import Base, engine
from app.models import Conflict, Dataset, EvalRun, Match, MatchJob, Record  # noqa: F401


def main():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.create_all(engine)
    print("Tables created:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()
