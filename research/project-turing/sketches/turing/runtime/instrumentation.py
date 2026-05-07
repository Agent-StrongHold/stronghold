"""Structured logging for the runtime.

Plain format for dev, JSON format for prod. Logger name convention
`turing.<module>`. `tick_count` extra injected on every record if caller
supplies it.
"""

from __future__ import annotations

import json
import logging
import sys
from logging.config import dictConfig


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("tick_count", "item_id", "chosen_pool", "provider"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", fmt: str = "plain") -> None:
    handler_class = "logging.StreamHandler"
    if fmt == "json":
        formatter = {"()": JsonFormatter}
    else:
        formatter = {
            "format": "%(asctime)s %(levelname)-8s %(name)s %(message)s",
        }
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": formatter},
            "handlers": {
                "console": {
                    "class": handler_class,
                    "level": level,
                    "formatter": "default",
                    "stream": sys.stderr,
                },
            },
            "loggers": {
                "turing": {
                    "level": level,
                    "handlers": ["console"],
                    "propagate": False,
                },
            },
        }
    )
