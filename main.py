import asyncio
import sys
import traceback

# Sandbox worker entry: when launched with --sandbox-worker we are an isolated
# code-execution subprocess. Dispatch before importing Qt/GUI modules so the
# worker stays minimal and holds none of the host's live objects.
if "--sandbox-worker" in sys.argv:
    from src.utils.sandbox_worker import main as _sandbox_worker_main

    sys.exit(_sandbox_worker_main())

from PyQt6 import QtWebEngineWidgets  # noqa: F401
from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.utils.app_logger import get_logger, setup_logging

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = setup_logging()


def _install_exception_hook():
    def _handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        app = QApplication.instance()
        if app is not None and not getattr(app, "closingDown", lambda: False)():
            QMessageBox.critical(
                None,
                "AudioMate Error",
                "AudioMate hit an unexpected error. Open the logs directory "
                "from the feedback menu and include the latest log when reporting it.",
            )
        else:
            traceback.print_exception(exc_type, exc_value, exc_traceback)

    sys.excepthook = _handle_exception


_install_exception_hook()

from src.gui.main_window import MainWindow
from src.services.single_instance import acquire_single_instance

logger = get_logger(__name__)


def main() -> int:
    logger.info("AudioMate starting")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    try:
        from src.gui.theme import DARK_STYLESHEET, STYLESHEET
        from src.utils.storage import load_app_settings

        theme_mode = load_app_settings().get("theme", "light")
        app.setStyleSheet(DARK_STYLESHEET if theme_mode == "dark" else STYLESHEET)
    except Exception:
        logger.exception("Failed to apply application stylesheet")

    server = acquire_single_instance()
    if server is None:
        logger.info("Another AudioMate instance is already running; exiting")
        return 0

    window = MainWindow()
    window.show()
    logger.info("Main window shown")

    exit_code = app.exec()
    logger.info("AudioMate exiting: code=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
