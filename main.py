import sys
import os
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Create assets directory if it doesn't exist
    if not os.path.exists("assets"):
        os.makedirs("assets")

    # The DatabaseManager now handles its own initialization of hierarchy.db.
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())