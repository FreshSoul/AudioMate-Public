"""Local plugin, skill, and REAPER setup operations for MainWindow."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from src.services.reaper_setup import ReaperSetupError, ReaperSetupService
from src.utils.app_logger import get_logger
from src.utils.plugin_store import import_plugin_directory, upsert_plugin_item
from src.utils.skill_store import import_skill_directory, upsert_skill_item


logger = get_logger(__name__)


class MarketOperations:
    """Own local extension lifecycle work for MainWindow."""

    def __init__(self, owner):
        self.owner = owner

    def import_plugin_from_dialog(self):
        directory = QFileDialog.getExistingDirectory(
            self.owner,
            "Select Plugin Directory",
            "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if directory:
            self.import_plugin_from_path(directory)

    def import_plugin_from_path(self, directory: str):
        owner = self.owner
        try:
            plugin_item = import_plugin_directory(directory)
            updated = upsert_plugin_item(owner.app_settings.get("plugins"), plugin_item)
            owner.apply_plugin_settings(updated)
            QMessageBox.information(owner, "Plugin", f"Imported plugin: {plugin_item.get('name', '')}")
            self.refresh_market_catalog()
        except Exception as exc:
            QMessageBox.warning(owner, "Plugin Import Failed", str(exc))

    def import_bundled_plugin(self, relative_path: str):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        directory = os.path.abspath(os.path.join(base_dir, relative_path))
        self.import_plugin_from_path(directory)

    def open_reaper_setup(self):
        owner = self.owner
        service = ReaperSetupService(app_settings=owner.app_settings)
        status = service.status()
        summary = service.format_status(status)
        if not status.ready_to_configure:
            QMessageBox.warning(owner, "REAPER Setup", summary)
            return
        answer = QMessageBox.question(
            owner,
            "REAPER Setup",
            summary + "\n\nBack up the REAPER configuration and write the recommended Python bridge settings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = service.configure()
        except ReaperSetupError as exc:
            QMessageBox.warning(owner, "REAPER Setup Failed", str(exc))
            return
        except Exception as exc:
            logger.exception("REAPER setup failed")
            QMessageBox.warning(owner, "REAPER Setup Failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            owner,
            "REAPER Setup Complete",
            "REAPER Python settings and the AudioMate bootstrap were installed.\n\n"
            f"Backup: {result.get('backup')}\n"
            f"Bootstrap: {result.get('bootstrap')}\n\n"
            "Restart REAPER, then run AudioMate/audiomate_reapy_bootstrap.py from the Action List once.",
        )

    def import_skill_from_dialog(self):
        owner = self.owner
        directory = QFileDialog.getExistingDirectory(
            owner,
            "Select Skill Directory",
            "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if not directory:
            return
        try:
            skill_item = import_skill_directory(directory)
            updated = upsert_skill_item(owner.app_settings.get("skills"), skill_item)
            owner.apply_skill_settings(updated)
            QMessageBox.information(owner, "Skill", f"Imported skill: {skill_item.get('name', '')}")
            self.refresh_market_catalog()
        except Exception as exc:
            QMessageBox.warning(owner, "Skill Import Failed", str(exc))

    def refresh_market_catalog(self):
        owner = self.owner
        if not hasattr(owner, "market_page"):
            return

        plugins = [
            {
                "section": "plugin",
                "title": "Import Plugin Directory",
                "description": "Load a local plugin folder that contains plugin.json and its Python entry file.",
                "category": "Local Plugin",
                "kind": "plugin",
            },
            {
                "section": "plugin",
                "title": "Reaper Control",
                "description": "Bundled REAPER control plugin with transport, track, MIDI, render, and project tools.",
                "category": "Bundled Plugin",
                "kind": "bundled_plugin",
                "id": "reaper-control",
                "path": "plugins/reaper-control-plugin",
            },
        ]
        skills = [
            {
                "section": "skill",
                "title": "Import Skill Directory",
                "description": "Load a local skill folder that contains SKILL.md and optional skill.json metadata.",
                "category": "Local Skill",
                "kind": "skill",
            }
        ]
        owner.market_page.set_catalog("", skills=skills, plugins=plugins)
        owner.market_page.set_status("", "idle")
