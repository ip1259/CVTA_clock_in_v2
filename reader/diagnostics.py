"""Persistent diagnostics for the windowed desktop reader client."""

import faulthandler
import logging
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from log_config import setup_logging


_crash_file = None
_qt_handler = None


def client_log_dir() -> Path:
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".cvta-clock-in")
    return root / "CVTAClockIn" / "logs"


def setup_client_diagnostics() -> Path:
    """Install file logging before constructing any Qt application objects."""
    global _crash_file, _qt_handler

    log_dir = client_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(str(log_dir))

    # Keep the file object alive for the process lifetime. faulthandler writes
    # directly to its file descriptor when Python's logging cannot run.
    _crash_file = open(log_dir / "crash.log", "a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_crash_file, all_threads=True)

    def unhandled_exception(exc_type, exc_value, exc_traceback):
        logging.getLogger("reader.unhandled").critical(
            "Unhandled main-thread exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    def thread_exception(args):
        logging.getLogger("reader.unhandled").critical(
            "Unhandled Python thread exception in %s", args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = unhandled_exception
    threading.excepthook = thread_exception

    def qt_message_handler(message_type, context, message):
        level = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }.get(message_type, logging.ERROR)
        logging.getLogger("reader.qt").log(level, "%s", message)

    _qt_handler = qt_message_handler
    qInstallMessageHandler(_qt_handler)
    return log_dir
