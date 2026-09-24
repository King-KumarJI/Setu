"""
Application entry point.
"""
from __future__ import annotations

import sys

from app.utils.logging import get_logger

logger = get_logger("setu")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    logger.info("Setu started.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
