"""Image sources, visual indexing jobs and recoverable image-vector metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0003_images"
down_revision = "0002_retrieval"
branch_labels = None
depends_on = None


def rebuild(expanded):
    connection = op.get_bind()
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("use the supported migration connection for parent table rebuilds")
    triggers = connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='trigger'").all()
    sequences = dict(connection.exec_driver_sql("SELECT name, seq FROM sqlite_sequence WHERE name IN ('sources','indexing_jobs')").all())
    for name, _ in triggers:
        connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
    types = "'pdf','txt','markdown','docx','note','image'" if expanded else "'pdf','txt','markdown','docx','note'"
    stages = "'ingestion','indexing','visual'" if expanded else "'ingestion','indexing'"
    with op.batch_alter_table("sources", recreate="always", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_constraint(op.f("ck_sources_source_type"), type_="check")
        batch.create_check_constraint(op.f("ck_sources_source_type"), f"source_type IN ({types})")
    with op.batch_alter_table("indexing_jobs", recreate="always", table_kwargs={"sqlite_autoincrement": True}) as batch:
        stage_names = [c["name"] for c in sa.inspect(connection).get_check_constraints("indexing_jobs")
                       if "stage IN" in c["sqltext"]]
        for name in stage_names:
            batch.drop_constraint(op.f(name), type_="check")
        batch.create_check_constraint(op.f("ck_indexing_jobs_stage"), f"stage IN ({stages})")
    for _, sql in triggers:
        connection.exec_driver_sql(sql)
    for table, sequence in sequences.items():
        connection.exec_driver_sql("UPDATE sqlite_sequence SET seq=max(seq, ?) WHERE name=?", (sequence, table))


def upgrade():
    rebuild(True)
    op.create_table("image_embedding_records",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("dimension > 0", name=op.f("ck_image_embedding_records_dimension")),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_image_embedding_records_source_id_sources", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", name="pk_image_embedding_records"))


def downgrade():
    connection = op.get_bind()
    if connection.exec_driver_sql("SELECT 1 FROM sources WHERE source_type='image' LIMIT 1").first():
        raise RuntimeError("remove image sources explicitly before downgrading")
    op.drop_table("image_embedding_records")
    rebuild(False)
