import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.utils import app_logger


class AppLoggerTests(unittest.TestCase):
    def tearDown(self):
        self._remove_app_handlers()

    def _remove_app_handlers(self):
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if getattr(handler, "name", "") in {
                app_logger._FILE_HANDLER_NAME,
                app_logger._STREAM_HANDLER_NAME,
            }:
                root_logger.removeHandler(handler)
                handler.close()

    def test_setup_logging_creates_log_file(self):
        self._remove_app_handlers()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                logger = app_logger.setup_logging(log_dir=temp_dir)
                logger.info("hello from test")
                for handler in logging.getLogger().handlers:
                    handler.flush()

                log_file = Path(temp_dir) / "audiomate.log"
                self.assertTrue(log_file.exists())
                self.assertIn("hello from test", log_file.read_text(encoding="utf-8"))
            finally:
                self._remove_app_handlers()

    def test_setup_logging_does_not_duplicate_handlers(self):
        self._remove_app_handlers()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                app_logger.setup_logging(log_dir=temp_dir)
                app_logger.setup_logging(log_dir=temp_dir)

                app_handlers = [
                    handler
                    for handler in logging.getLogger().handlers
                    if getattr(handler, "name", "")
                    in {app_logger._FILE_HANDLER_NAME, app_logger._STREAM_HANDLER_NAME}
                ]
                self.assertEqual(len(app_handlers), 2)
            finally:
                self._remove_app_handlers()

    def test_get_logs_dir_uses_storage_base_dir(self):
        self.assertTrue(app_logger.get_logs_dir().endswith("logs"))
        self.assertTrue(app_logger.get_logs_dir().startswith(app_logger.BASE_DIR))

    def test_open_logs_dir_creates_directory_without_launching(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / "logs"
            with mock.patch.object(app_logger.sys, "platform", "win32"), mock.patch.object(
                app_logger.os,
                "startfile",
                autospec=True,
                create=True,
            ) as startfile:
                result = app_logger.open_logs_dir(logs_dir)

            self.assertEqual(result, str(logs_dir))
            self.assertTrue(logs_dir.exists())
            startfile.assert_called_once_with(str(logs_dir))


if __name__ == "__main__":
    unittest.main()
