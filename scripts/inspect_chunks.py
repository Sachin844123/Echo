"""Inspect local chunk metadata; text output requires explicit --show-text."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import configure_logging
from app.database.engine import create_sqlite_engine
from app.database.migrate import check_database
from app.database.models import Chunk, Document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--show-text", action="store_true", help="Explicitly print private chunk text to this terminal")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or (args.source_id is not None and args.source_id < 1):
        parser.error("require a positive source ID and a limit between 1 and 100")
    configure_logging()
    settings = Settings.from_env()
    if not settings.database_path.is_file():
        parser.error("database is missing; run python -m app migrate first")
    engine = create_sqlite_engine(settings.database_path)
    try:
        check_database(engine)
        query = select(Chunk, Document.source_id).join(Document).order_by(Chunk.id).limit(args.limit)
        if args.source_id is not None:
            query = query.where(Document.source_id == args.source_id)
        with Session(engine) as session:
            for chunk, source_id in session.execute(query):
                row = {"source_id": source_id, "chunk_id": chunk.id, "chunk_index": chunk.chunk_index,
                       "token_count": chunk.token_count, "page_number": chunk.page_number,
                       "start_offset": chunk.start_offset, "end_offset": chunk.end_offset}
                if args.show_text:
                    row.update(text=chunk.chunk_text, heading=chunk.heading)
                print(json.dumps(row, ensure_ascii=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
