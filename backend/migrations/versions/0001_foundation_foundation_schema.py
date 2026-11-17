"""Foundation schema"""
from alembic import op
import sqlalchemy as sa


revision = '0001_foundation'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('length(trim(key)) > 0', name=op.f('ck_app_settings_key_not_blank')),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_app_settings'))
    )
    op.create_table('collections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('length(trim(name)) > 0', name=op.f('ck_collections_name_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collections')),
    sa.UniqueConstraint('name', name=op.f('uq_collections_name')),
    sqlite_autoincrement=True
    )
    op.create_table('sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_type', sa.String(length=20), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('original_url', sa.Text(), nullable=True),
    sa.Column('file_path', sa.Text(), nullable=True),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('captured_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('indexed_at', sa.DateTime(), nullable=True),
    sa.Column('processing_status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'", name=op.f('ck_sources_sha256')),
    sa.CheckConstraint("processing_status IN ('pending','processing','indexed','failed')", name=op.f('ck_sources_processing_status')),
    sa.CheckConstraint("source_type IN ('pdf','txt','markdown','docx','note')", name=op.f('ck_sources_source_type')),
    sa.CheckConstraint('is_deleted IN (0,1)', name=op.f('ck_sources_is_deleted')),
    sa.CheckConstraint('length(trim(title)) > 0', name=op.f('ck_sources_title_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sources')),
    sa.UniqueConstraint('content_hash', name=op.f('uq_sources_content_hash')),
    sqlite_autoincrement=True
    )
    op.create_index(op.f('ix_sources_captured_at'), 'sources', ['captured_at'], unique=False)
    op.create_index(op.f('ix_sources_is_deleted'), 'sources', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_sources_processing_status'), 'sources', ['processing_status'], unique=False)
    op.create_index('ix_sources_type_captured', 'sources', ['source_type', 'captured_at'], unique=False)
    op.create_table('collection_items',
    sa.Column('collection_id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], name=op.f('fk_collection_items_collection_id_collections'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_collection_items_source_id_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'source_id', name=op.f('pk_collection_items'))
    )
    op.create_index(op.f('ix_collection_items_source_id'), 'collection_items', ['source_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('extracted_text', sa.Text(), nullable=False),
    sa.Column('language', sa.String(length=35), nullable=True),
    sa.Column('extraction_method', sa.String(length=50), nullable=False),
    sa.Column('extraction_status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('content_length', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("extraction_status IN ('pending','complete','failed')", name=op.f('ck_documents_extraction_status')),
    sa.CheckConstraint('content_length >= 0', name=op.f('ck_documents_content_length')),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_documents_source_id_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('source_id', name=op.f('uq_documents_source_id')),
    sqlite_autoincrement=True
    )
    op.create_table('indexing_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('pending','running','succeeded','failed')", name=op.f('ck_indexing_jobs_status')),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_indexing_jobs_attempts')),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_indexing_jobs_source_id_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indexing_jobs')),
    sqlite_autoincrement=True
    )
    op.create_index(op.f('ix_indexing_jobs_source_id'), 'indexing_jobs', ['source_id'], unique=False)
    op.create_index('ix_indexing_jobs_status_created', 'indexing_jobs', ['status', 'created_at'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('chunk_text', sa.Text(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('heading', sa.Text(), nullable=True),
    sa.Column('start_offset', sa.Integer(), nullable=False),
    sa.Column('end_offset', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('chunk_index >= 0', name=op.f('ck_chunks_chunk_index')),
    sa.CheckConstraint('length(trim(chunk_text)) > 0', name=op.f('ck_chunks_text_not_blank')),
    sa.CheckConstraint('page_number IS NULL OR page_number > 0', name=op.f('ck_chunks_page_number')),
    sa.CheckConstraint('start_offset >= 0 AND end_offset > start_offset', name=op.f('ck_chunks_offsets')),
    sa.CheckConstraint('token_count > 0', name=op.f('ck_chunks_token_count')),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name=op.f('uq_chunks_document_id')),
    sqlite_autoincrement=True
    )
    op.create_table('embedding_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chunk_id', sa.Integer(), nullable=False),
    sa.Column('model_name', sa.String(length=200), nullable=False),
    sa.Column('model_version', sa.String(length=100), nullable=False),
    sa.Column('vector_index_id', sa.Integer(), nullable=False),
    sa.Column('dimension', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('dimension > 0', name=op.f('ck_embedding_records_dimension')),
    sa.CheckConstraint('length(trim(model_name)) > 0 AND length(trim(model_version)) > 0', name=op.f('ck_embedding_records_model_identity')),
    sa.CheckConstraint('vector_index_id = chunk_id', name=op.f('ck_embedding_records_vector_is_chunk_id')),
    sa.ForeignKeyConstraint(['chunk_id'], ['chunks.id'], name=op.f('fk_embedding_records_chunk_id_chunks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_embedding_records')),
    sa.UniqueConstraint('chunk_id', name=op.f('uq_embedding_records_chunk_id')),
    sa.UniqueConstraint('vector_index_id', name=op.f('uq_embedding_records_vector_index_id')),
    sqlite_autoincrement=True
    )

    # Maintain modification timestamps even for writes outside the ORM.
    for table, key in (("sources", "id"), ("collections", "id"),
                       ("indexing_jobs", "id"), ("app_settings", "key")):
        op.execute(f"""
            CREATE TRIGGER {table}_updated_at
            AFTER UPDATE ON {table}
            WHEN NEW.updated_at = OLD.updated_at
                 AND NEW.updated_at <> strftime('%Y-%m-%d %H:%M:%f', 'now')
            BEGIN
                UPDATE {table}
                SET updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')
                WHERE {key} = NEW.{key};
            END
        """)


def downgrade():
    op.drop_table('embedding_records')
    op.drop_table('chunks')
    op.drop_index('ix_indexing_jobs_status_created', table_name='indexing_jobs')
    op.drop_index(op.f('ix_indexing_jobs_source_id'), table_name='indexing_jobs')
    op.drop_table('indexing_jobs')
    op.drop_table('documents')
    op.drop_index(op.f('ix_collection_items_source_id'), table_name='collection_items')
    op.drop_table('collection_items')
    op.drop_index('ix_sources_type_captured', table_name='sources')
    op.drop_index(op.f('ix_sources_processing_status'), table_name='sources')
    op.drop_index(op.f('ix_sources_is_deleted'), table_name='sources')
    op.drop_index(op.f('ix_sources_captured_at'), table_name='sources')
    op.drop_table('sources')
    op.drop_table('collections')
    op.drop_table('app_settings')
