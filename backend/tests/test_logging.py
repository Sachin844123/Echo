import io
import json
import logging
import sys

from app.core.logging import SafeJsonFormatter


def test_structured_logs_never_render_untrusted_content():
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(SafeJsonFormatter())
    logger = logging.Logger("isolated-test", level=logging.INFO)
    logger.addHandler(handler)
    private = "PRIVATE TEST CONTENT /path?q=secret Bearer token"
    logger.info("SQL parameters: %s", private)
    logger.info("request_complete", extra={
        "request_id": "a" * 32, "status_code": 200, "duration_ms": 1.5,
        "query": private, "token": private, "body": private,
    })
    try:
        raise RuntimeError(private)
    except RuntimeError:
        logger.error("request_failed", exc_info=sys.exc_info())
    logs = [json.loads(line) for line in output.getvalue().splitlines()]
    assert logs[0]["event"] == "redacted_event"
    assert logs[1]["status_code"] == 200
    assert logs[1]["request_id"] == "a" * 32
    assert logs[2]["error_type"] == "RuntimeError"
    assert private not in output.getvalue()
    assert "Traceback" not in output.getvalue()
    assert all("timestamp" in event and "level" in event for event in logs)
