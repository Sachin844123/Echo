"""Allowlisted JSON logs: never format arbitrary message/exception content."""

import json
import logging
import sys
from datetime import datetime, timezone


EVENTS = frozenset({
    "startup_complete", "shutdown_complete", "startup_failed", "request_complete",
    "request_failed", "database_unavailable", "migration_complete", "command_failed",
    "job_succeeded", "job_failed", "worker_failed", "jobs_recovered",
})


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.msg if isinstance(record.msg, str) and record.msg in EVENTS else "redacted_event",
        }
        for name in ("status_code", "duration_ms", "job_id", "source_id"):
            value = getattr(record, name, None)
            if isinstance(value, (int, float)):
                payload[name] = value
        request_id = getattr(record, "request_id", "")
        if isinstance(request_id, str) and len(request_id) == 32 and all(c in "0123456789abcdef" for c in request_id):
            payload["request_id"] = request_id
        # Exception class alone is useful; messages, traceback and locals may contain documents.
        if record.exc_info and record.exc_info[0]:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(SafeJsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "alembic"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
