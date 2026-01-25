import os
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from db import DatabaseClient
from main_window_viewer import MainWindowViewer


def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def main():
    conn_str = (
        "x"
        "y"
        "z"
    )

    app = QApplication(sys.argv)

    icon_path = resource_path("ROITempViewer.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    try:
        db_client = DatabaseClient(conn_str)
        _ = db_client.get_sessions() 
    except Exception as e:
        QMessageBox.critical(
            None,
            "Błąd połączenia z bazą danych",
            (
                f"Nie udało się połączyć z bazą danych:\n{e}\n"
                "Upewnij się, że projekt Supabase nie jest uśpiony / "
                "że connection string jest poprawny."
            ),
        )
        return

    win = MainWindowViewer(db_client)

    if os.path.exists(icon_path):
        win.setWindowIcon(QIcon(icon_path))

    win.resize(1200, 700)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
