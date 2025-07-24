from PyQt6.QtWidgets import QMessageBox

def show_info_dialog(parent, title, message):
    """Displays an informational message box."""
    QMessageBox.information(parent, title, message)

def show_warning_dialog(parent, title, message):
    """Displays a warning message box."""
    QMessageBox.warning(parent, title, message)

def show_critical_dialog(parent, title, message):
    """Displays a critical error message box."""
    QMessageBox.critical(parent, title, message)

def show_question_dialog(parent, title, message):
    """
    Asks a yes/no question and returns True for Yes, False for No.
    """
    reply = QMessageBox.question(parent, title, message,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return reply == QMessageBox.StandardButton.Yes

def show_about_dialog(parent, title, message):
    """Displays an 'About' dialog."""
    QMessageBox.about(parent, title, message)