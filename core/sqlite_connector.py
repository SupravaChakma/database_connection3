# sqlite_connector.py
import sqlite3 as sqlite
import os
from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QHBoxLayout, QPushButton, QVBoxLayout, QMessageBox, QFileDialog
from PyQt6.QtGui import QIcon, QStandardItem
from PyQt6.QtCore import Qt

from core.db_connections import DBConnector

class SQLiteConnectionDialog(QDialog):
    def __init__(self, parent=None, conn_data=None):
        super().__init__(parent)
        self.conn_data = conn_data
        is_editing = self.conn_data is not None

        self.setWindowTitle(
            "Edit SQLite Connection" if is_editing else "New SQLite Connection")

        self.name_input = QLineEdit()
        self.path_input = QLineEdit()

        form = QFormLayout()
        form.addRow("Connection Name:", self.name_input)
        form.addRow("Database Path:", self.path_input)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_file)
        self.create_btn = QPushButton("Create New DB")
        self.create_btn.clicked.connect(self.create_new_db)

        path_layout = QHBoxLayout()
        path_layout.addWidget(self.browse_btn)
        path_layout.addWidget(self.create_btn)
        form.addRow("", path_layout)

        if is_editing:
            self.name_input.setText(self.conn_data.get("name", ""))
            self.path_input.setText(self.conn_data.get("db_path", ""))

        self.save_btn = QPushButton("Update" if is_editing else "Save")
        self.save_btn.clicked.connect(self.save_connection)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select SQLite DB", "", "SQLite Database (*.db *.sqlite *.sqlite3)")
        if file_path:
            self.path_input.setText(file_path)

    def create_new_db(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Create New SQLite DB", "", "SQLite Database (*.db *.sqlite *.sqlite3)")
        if file_path:
            try:
                conn = sqlite.connect(file_path)
                conn.close()
                self.path_input.setText(file_path)
                QMessageBox.information(
                    self, "Success", f"Database created successfully at:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create database:\n{e}")

    def save_connection(self):
        if not self.name_input.text().strip() or not self.path_input.text().strip():
            QMessageBox.warning(self, "Missing Info", "Both fields are required.")
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_input.text(),
            "db_path": self.path_input.text(),
            "id": self.conn_data.get("id") if self.conn_data else None
        }


class SQLiteConnector(DBConnector):
    def connect(self, conn_data):
        db_path = conn_data.get("db_path")
        if not db_path or not os.path.exists(db_path):
            raise ConnectionError(f"SQLite DB path not found: {db_path}")
        return sqlite.connect(db_path)

    def close(self, conn):
        if conn:
            conn.close()

    def execute_query(self, conn, query):
        cursor = conn.cursor()
        cursor.execute(query)

        is_select_query = query.lower().strip().startswith("select")
        results = []
        columns = []
        row_count = 0

        if is_select_query:
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                results = cursor.fetchall()
                row_count = len(results)
        else:
            conn.commit()
            row_count = cursor.rowcount if cursor.rowcount != -1 else 0
        
        return results, columns, row_count, is_select_query

    def load_schema(self, conn_data, schema_model, status_callback):
        schema_model.clear()
        schema_model.setHorizontalHeaderLabels(["Tables & Views"])
        db_path = conn_data.get("db_path")
        if not db_path or not os.path.exists(db_path):
            status_callback(f"Error: SQLite DB path not found: {db_path}", 5000)
            return

        try:
            conn = self.connect(conn_data)
            cursor = conn.cursor()
            cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name;")
            tables = cursor.fetchall()
            self.close(conn)
            for name, type in tables:
                icon = QIcon("assets/table_icon.png") if type == 'table' else QIcon("assets/view_icon.png")
                item = QStandardItem(icon, name)
                item.setEditable(False)
                item.setData({'db_type': 'sqlite', 'conn_data': conn_data}, Qt.ItemDataRole.UserRole)
                schema_model.appendRow(item)
        except Exception as e:
            status_callback(f"Error loading SQLite schema: {e}", 5000)

    def get_connection_dialog(self, parent=None, conn_data=None, is_editing=False):
        return SQLiteConnectionDialog(parent, conn_data)