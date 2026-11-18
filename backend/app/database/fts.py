"""Content-bearing FTS5 with triggers and explicit drift repair."""

from sqlalchemy import Connection
from sqlalchemy.exc import DatabaseError

TABLE_SQL = "CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_text, title, heading, tokenize='unicode61 remove_diacritics 2')"
CONTENT_SQL = """SELECT c.id, c.chunk_text, s.title, coalesce(c.heading, '')
    FROM chunks c JOIN documents d ON d.id=c.document_id JOIN sources s ON s.id=d.source_id"""
TRIGGERS = {
    "chunks_fts_ai": """CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunk_fts(rowid,chunk_text,title,heading)
        SELECT new.id,new.chunk_text,s.title,coalesce(new.heading,'')
        FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.id=new.document_id;
    END""",
    "chunks_fts_ad": """CREATE TRIGGER chunks_fts_ad AFTER DELETE ON chunks BEGIN
        DELETE FROM chunk_fts WHERE rowid=old.id;
    END""",
    "chunks_fts_au": """CREATE TRIGGER chunks_fts_au AFTER UPDATE ON chunks BEGIN
        DELETE FROM chunk_fts WHERE rowid=old.id;
        INSERT INTO chunk_fts(rowid,chunk_text,title,heading)
        SELECT new.id,new.chunk_text,s.title,coalesce(new.heading,'')
        FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.id=new.document_id;
        DELETE FROM embedding_records WHERE chunk_id=new.id AND old.chunk_text<>new.chunk_text;
    END""",
    "sources_fts_title": """CREATE TRIGGER sources_fts_title AFTER UPDATE OF title ON sources BEGIN
        UPDATE chunk_fts SET title=new.title WHERE rowid IN
        (SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.source_id=new.id);
    END""",
    "documents_fts_source": """CREATE TRIGGER documents_fts_source AFTER UPDATE OF source_id ON documents BEGIN
        UPDATE chunk_fts SET title=(SELECT title FROM sources WHERE id=new.source_id)
        WHERE rowid IN (SELECT id FROM chunks WHERE document_id=new.id);
    END""",
}


def reconcile_fts(connection: Connection) -> bool:
    repaired = False
    exists = connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'").first()
    if not exists:
        connection.exec_driver_sql(TABLE_SQL)
        repaired = True
    for name, expected in TRIGGERS.items():
        current = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).scalar()
        if current != expected:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
            connection.exec_driver_sql(expected)
            repaired = True
    try:
        connection.exec_driver_sql("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")
        left = connection.exec_driver_sql(f"SELECT rowid,chunk_text,title,heading FROM chunk_fts EXCEPT {CONTENT_SQL} LIMIT 1").first()
        right = connection.exec_driver_sql(f"{CONTENT_SQL} EXCEPT SELECT rowid,chunk_text,title,heading FROM chunk_fts LIMIT 1").first()
        repaired = repaired or left is not None or right is not None
    except DatabaseError:
        connection.exec_driver_sql("DROP TABLE chunk_fts")
        connection.exec_driver_sql(TABLE_SQL)
        repaired = True
    if repaired:
        connection.exec_driver_sql("DELETE FROM chunk_fts")
        connection.exec_driver_sql(f"INSERT INTO chunk_fts(rowid,chunk_text,title,heading) {CONTENT_SQL}")
    return repaired
