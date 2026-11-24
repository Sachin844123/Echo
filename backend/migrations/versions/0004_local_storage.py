"""Persist explicit local consent and automatic file references."""
from alembic import op
import sqlalchemy as sa

revision = "0004_local_storage"
down_revision = "0003_images"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column(name, sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp())
            for name in ("created_at", "updated_at")]


def upgrade():
    op.add_column("sources", sa.Column("manual_capture", sa.Boolean(), nullable=False, server_default="1"))
    op.create_table(
        "local_access", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False), sa.Column("state", sa.String(20), nullable=False),
        *(sa.Column(name, sa.Text(), nullable=False) for name in ("roots", "exclusions", "extensions")),
        *timestamps(),
        sa.CheckConstraint("id = 1", name=op.f("ck_local_access_singleton")),
        sa.CheckConstraint("mode IN ('all', 'personal', 'selected', 'deny')", name=op.f("ck_local_access_mode")),
        sa.CheckConstraint("state IN ('active', 'paused', 'cancelled')", name=op.f("ck_local_access_state")),
    )
    op.create_table(
        "local_files", sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("mtime_ns", sa.Integer(), nullable=False),
        sa.Column("identity", sa.String(100), nullable=False), *timestamps(),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_local_files_size_bytes")),
    )
    op.create_index("ix_local_files_source_id", "local_files", ["source_id"])


def downgrade():
    connection = op.get_bind()
    if connection.exec_driver_sql("SELECT 1 FROM sources WHERE manual_capture=0 LIMIT 1").first():
        raise RuntimeError("revoke local storage access and finish cleanup before downgrading")
    op.drop_table("local_files")
    op.drop_table("local_access")
    op.drop_column("sources", "manual_capture")
