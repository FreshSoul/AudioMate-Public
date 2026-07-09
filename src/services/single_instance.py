"""Single-instance guard for the desktop application."""

from __future__ import annotations

import getpass
from typing import Optional

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

try:
    _USER_TAG = getpass.getuser() or "default"
except Exception:
    _USER_TAG = "default"

SOCKET_NAME = f"AudioMate-IPC-{_USER_TAG}"
_CONNECT_TIMEOUT_MS = 500


class SingleInstanceServer(QObject):
    """Owns the local IPC server that marks this process as the main instance."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        QLocalServer.removeServer(SOCKET_NAME)
        if not self._server.listen(SOCKET_NAME):
            raise RuntimeError(
                f"Unable to listen on local socket {SOCKET_NAME}: {self._server.errorString()}"
            )


def _another_instance_is_running() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    connected = socket.waitForConnected(_CONNECT_TIMEOUT_MS)
    if connected:
        socket.disconnectFromServer()
    return connected


def acquire_single_instance() -> Optional[SingleInstanceServer]:
    """Return a server for the main instance, or None when one already exists."""

    if _another_instance_is_running():
        return None
    try:
        return SingleInstanceServer()
    except RuntimeError:
        if _another_instance_is_running():
            return None
        raise
