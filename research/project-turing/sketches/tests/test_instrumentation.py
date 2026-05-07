"""Tests for turing/runtime/instrumentation.py — setup_logging and JsonFormatter.

Spec:
    setup_logging configures the turing logger hierarchy with either plain
    or JSON formatting. JsonFormatter produces valid JSON with structured
    fields.

Acceptance criteria:
    1. setup_logging with fmt="plain" configures a StreamHandler with a
       standard format string.
    2. setup_logging with fmt="json" configures a StreamHandler using
       JsonFormatter.
    3. JsonFormatter.format() produces valid JSON with ts, level, logger, msg.
    4. JsonFormatter includes tick_count, item_id, chosen_pool, provider
       when present as extra attributes.
    5. JsonFormatter includes exc when exception info is present.
"""

from __future__ import annotations

import json
import logging

from turing.runtime.instrumentation import JsonFormatter, setup_logging


class TestJsonFormatter:
    def test_basic_record_produces_valid_json(self) -> None:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=None,
            exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["msg"] == "hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "turing.test"
        assert "ts" in data

    def test_extra_tick_count_included(self) -> None:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="tick",
            args=None,
            exc_info=None,
        )
        record.tick_count = 42
        output = fmt.format(record)
        data = json.loads(output)
        assert data["tick_count"] == 42

    def test_extra_item_id_included(self) -> None:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="item",
            args=None,
            exc_info=None,
        )
        record.item_id = "abc-123"
        output = fmt.format(record)
        data = json.loads(output)
        assert data["item_id"] == "abc-123"

    def test_extra_chosen_pool_included(self) -> None:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="routed",
            args=None,
            exc_info=None,
        )
        record.chosen_pool = "gemini-flash"
        output = fmt.format(record)
        data = json.loads(output)
        assert data["chosen_pool"] == "gemini-flash"

    def test_extra_provider_included(self) -> None:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="provider",
            args=None,
            exc_info=None,
        )
        record.provider = "google"
        output = fmt.format(record)
        data = json.loads(output)
        assert data["provider"] == "google"

    def test_exception_info_included(self) -> None:
        fmt = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="failed",
            args=None,
            exc_info=exc_info,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exc" in data
        assert "ValueError" in data["exc"]
        assert "test error" in data["exc"]

    def test_no_extras_omitted(self) -> None:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="turing.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="plain",
            args=None,
            exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "tick_count" not in data
        assert "item_id" not in data
        assert "exc" not in data


class TestSetupLogging:
    def test_plain_format_configures_logger(self) -> None:
        setup_logging(level="DEBUG", fmt="plain")
        logger = logging.getLogger("turing")
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) > 0

    def test_json_format_configures_logger(self) -> None:
        setup_logging(level="WARNING", fmt="json")
        logger = logging.getLogger("turing")
        assert logger.level == logging.WARNING
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_plain_format_emits_output(self, capsys) -> None:
        setup_logging(level="DEBUG", fmt="plain")
        logger = logging.getLogger("turing.test_output_plain")
        logger.info("test plain message")
        captured = capsys.readouterr()
        assert "test plain message" in captured.err

    def test_json_format_emits_valid_json(self, capsys) -> None:
        setup_logging(level="DEBUG", fmt="json")
        logger = logging.getLogger("turing.test_output_json")
        logger.info("test json message")
        captured = capsys.readouterr()
        data = json.loads(captured.err.strip().split("\n")[-1])
        assert data["msg"] == "test json message"
