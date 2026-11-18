"""Add durable indexing stages, embedding fingerprints and synchronized FTS5."""
from alembic import op
import sqlalchemy as sa

revision = "0002_retrieval"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

TABLE_SQL = "CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_text, title, heading, tokenize='unicode61 remove_diacritics 2')"

CONTENT_SQL = "SELECT c.id, c.chunk_text, s.title, coalesce(c.heading, '')\n    FROM chunks c JOIN documents d ON d.id=c.document_id JOIN sources s ON s.id=d.source_id"

TRIGGERS = {'chunks_fts_ai': "CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN\n        INSERT INTO chunk_fts(rowid,chunk_text,title,heading)\n        SELECT new.id,new.chunk_text,s.title,coalesce(new.heading,'')\n        FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.id=new.document_id;\n    END", 'chunks_fts_ad': 'CREATE TRIGGER chunks_fts_ad AFTER DELETE ON chunks BEGIN\n        DELETE FROM chunk_fts WHERE rowid=old.id;\n    END', 'chunks_fts_au': "CREATE TRIGGER chunks_fts_au AFTER UPDATE ON chunks BEGIN\n        DELETE FROM chunk_fts WHERE rowid=old.id;\n        INSERT INTO chunk_fts(rowid,chunk_text,title,heading)\n        SELECT new.id,new.chunk_text,s.title,coalesce(new.heading,'')\n        FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.id=new.document_id;\n        DELETE FROM embedding_records WHERE chunk_id=new.id AND old.chunk_text<>new.chunk_text;\n    END", 'sources_fts_title': 'CREATE TRIGGER sources_fts_title AFTER UPDATE OF title ON sources BEGIN\n        UPDATE chunk_fts SET title=new.title WHERE rowid IN\n        (SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.source_id=new.id);\n    END', 'documents_fts_source': 'CREATE TRIGGER documents_fts_source AFTER UPDATE OF source_id ON documents BEGIN\n        UPDATE chunk_fts SET title=(SELECT title FROM sources WHERE id=new.source_id)\n        WHERE rowid IN (SELECT id FROM chunks WHERE document_id=new.id);\n    END'}

def upgrade():
    op.add_column("indexing_jobs", sa.Column("stage", sa.String(20), sa.CheckConstraint("stage IN ('ingestion','indexing')", name="ck_indexing_jobs_stage"), nullable=False, server_default="ingestion"))
    op.create_index("ix_indexing_jobs_stage_status", "indexing_jobs", ["stage", "status"])
    op.add_column("embedding_records", sa.Column("content_hash", sa.String(64), nullable=False, server_default=""))
    connection = op.get_bind()
    connection.exec_driver_sql(TABLE_SQL)
    for statement in TRIGGERS.values():
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql("INSERT INTO chunk_fts(rowid,chunk_text,title,heading) " + CONTENT_SQL)


def downgrade():
    connection = op.get_bind()
    for name in TRIGGERS:
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS " + name)
    connection.exec_driver_sql("DROP TABLE IF EXISTS chunk_fts")
    op.drop_index("ix_indexing_jobs_stage_status", table_name="indexing_jobs")
    # SQLite 3.35+ supports DROP COLUMN without rebuilding parent tables/cascades.
    connection.exec_driver_sql("ALTER TABLE embedding_records DROP COLUMN content_hash")
    connection.exec_driver_sql("ALTER TABLE indexing_jobs DROP COLUMN stage")
