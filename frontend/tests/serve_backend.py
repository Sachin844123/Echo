"""Ephemeral real ECHO server for browser TEST DATA; never opens the user's library."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

import uvicorn
from app.core.config import Settings
from app.core.logging import configure_logging
from app.database.engine import create_sqlite_engine
from app.database.migrate import upgrade_database
from app.main import create_app


def main():
    configure_logging('ERROR')
    with tempfile.TemporaryDirectory(prefix='echo-browser-TEST-DATA-') as directory:
        data = Path(directory)
        settings = Settings(data_dir=data, port=8237, session_token=os.environ['ECHO_E2E_TOKEN'],
                            allowed_origins=('http://127.0.0.1:8237', 'http://127.0.0.1:8238'),
                            embedding_model_dir=data / 'missing-model')
        engine = create_sqlite_engine(settings.database_path)
        upgrade_database(engine)
        engine.dispose()
        uvicorn.run(create_app(settings), host='127.0.0.1', port=8237, proxy_headers=False,
                    access_log=False, log_config=None, server_header=False, date_header=False, ws='none')


if __name__ == '__main__':
    main()
