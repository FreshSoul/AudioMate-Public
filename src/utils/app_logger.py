"""Application logging helpers for AudioMate."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.utils.app_paths import DATA_ROOT as _DATA_ROOT, LOGS_DIR as _LOGS_DIR

# BASE_DIR is preserved as an alias because external callers / tests still
# read app_logger.BASE_DIR; in dev it equals the project root, in frozen
# builds it points at the user data dir.
BASE_DIR = str(_DATA_ROOT)
LOGS_DIR = str(_LOGS_DIR)
_LOGGER_NAME = "audiomate"
_FILE_HANDLER_NAME = "audiomate_file_handler"
_STREAM_HANDLER_NAME = "audiomate_stream_handler"
_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class LogDirectoryOpenError(RuntimeError):
    """Raised when the platform cannot open the logs directory."""


def get_logs_dir() -> str:
    """Return the directory where AudioMate writes runtime log files."""
    return LOGS_DIR


def ensure_logs_dir(log_dir: str | os.PathLike[str] | None = None) -> str:
    """Create and return the logs directory."""
    target = Path(log_dir or get_logs_dir())
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def _has_handler(logger: logging.Logger, handler_name: str) -> bool:
    return any(getattr(handler, "name", "") == handler_name for handler in logger.handlers)


def setup_logging(
    *,
    level: int | str = logging.INFO,
    log_dir: str | os.PathLike[str] | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure application-wide logging and return the AudioMate logger.

    The root logger receives the handlers so module loggers created with
    ``logging.getLogger(__name__)`` write to the same rotating file.
    Calling this function repeatedly is safe and will not duplicate handlers.
    """
    if isinstance(level, str):
        normalized_level = getattr(logging, level.upper(), logging.INFO)
    else:
        normalized_level = level

    resolved_log_dir = ensure_logs_dir(log_dir)
    log_path = os.path.join(resolved_log_dir, "audiomate.log")
    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATE_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(normalized_level)

    if not _has_handler(root_logger, _FILE_HANDLER_NAME):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.name = _FILE_HANDLER_NAME
        file_handler.setLevel(normalized_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if not _has_handler(root_logger, _STREAM_HANDLER_NAME):
        stream_handler = logging.StreamHandler()
        stream_handler.name = _STREAM_HANDLER_NAME
        stream_handler.setLevel(normalized_level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    logger = get_logger()
    logger.setLevel(normalized_level)
    logger.info("Logging initialized: %s", log_path)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return an AudioMate logger or one of its children."""
    if not name:
        return logging.getLogger(_LOGGER_NAME)
    if name == _LOGGER_NAME or name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def open_logs_dir(log_dir: str | os.PathLike[str] | None = None) -> str:
    """Open the logs directory with the platform file manager.

    Returns the resolved directory path. Raises ``LogDirectoryOpenError`` if the
    operating system rejects the request.
    """
    resolved_log_dir = ensure_logs_dir(log_dir)
    try:
        if sys.platform.startswith("win"):
            os.startfile(resolved_log_dir)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", resolved_log_dir])
        else:
            subprocess.Popen(["xdg-open", resolved_log_dir])
    except Exception as exc:
        raise LogDirectoryOpenError(str(exc)) from exc
    return resolved_log_dir
