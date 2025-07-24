# postgres_connector.py
import psycopg2
from PyQt6.QtWidgets import QDialog, QFormLayout, QLineEdit, QHBoxLayout, QPushButton, QVBoxLayout, QMessageBox
from PyQt6.QtGui import QIcon, QStandardItem
from PyQt6.QtCore import Qt, QModelIndex

from core.db_connections import DBConnector

class PostgresConnectionDialog(QDialog):
    def __init__(self, parent=None, is_editing=False):
        super().__init__(parent)
        self.setWindowTitle("New PostgreSQL Connection" if not is_editing else "Edit PostgreSQL Connection")

        self.name_input = QLineEdit()
        self.host_input = QLineEdit()
        self.port_input = QLineEdit()
        self.db_input = QLineEdit()
        self.user_input = QLineEdit()

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Connection Name:", self.name_input)
        form.addRow("Host:", self.host_input)
        form.addRow("Port:", self.port_input)
        form.addRow("Database:", self.db_input)
        form.addRow("User:", self.user_input)
        form.addRow("Password:", self.password_input)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self.test_connection)

        self.save_btn = QPushButton("Update" if is_editing else "Save")
        self.save_btn.clicked.connect(self.save_connection)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.test_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.save_btn)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def test_connection(self):
        try:
            conn = psycopg2.connect(
                host=self.host_input.text(),
                port=int(self.port_input.text()),
                database=self.db_input.text(),
                user=self.user_input.text(),
                password=self.password_input.text()
            )
            conn.close()
            QMessageBox.information(self, "Success", "Connection successful!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to connect:\n{e}")

    def save_connection(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Missing Info", "Connection name is required.")
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_input.text(),
            "host": self.host_input.text(),
            "port": self.port_input.text(),
            "database": self.db_input.text(),
            "user": self.user_input.text(),
            "password": self.password_input.text()
        }


class PostgresConnector(DBConnector):
    def __init__(self):
        self.pg_conn = None # Store the connection for schema Browse

    def connect(self, conn_data):
        return psycopg2.connect(
            host=conn_data["host"], database=conn_data["database"],
            user=conn_data["user"], password=conn_data["password"],
            port=int(conn_data["port"])
        )

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

    def load_schema(self, conn_data, schema_model, status_callback, schema_tree_expanded_signal_connect_callback):
        try:
            schema_model.clear()
            schema_model.setHorizontalHeaderLabels(["Schemas"])
            
            # Close existing schema connection if open
            if self.pg_conn:
                self.pg_conn.close()

            self.pg_conn = self.connect(conn_data) # Re-establish connection for schema Browse
            cursor = self.pg_conn.cursor()
            cursor.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast') ORDER BY schema_name;")
            schemas = cursor.fetchall()
            for (schema_name,) in schemas:
                schema_item = QStandardItem(QIcon("assets/schema_icon.png"), schema_name)
                schema_item.setEditable(False)
                item_data = {'db_type': 'postgres', 'schema_name': schema_name, 'conn_data': conn_data}
                schema_item.setData(item_data, Qt.ItemDataRole.UserRole)
                schema_item.appendRow(QStandardItem("Loading...")) # Placeholder for expansion
                schema_model.appendRow(schema_item)
            
            # Connect the expanded signal after populating schemas
            schema_tree_expanded_signal_connect_callback(self.load_tables_on_expand)

        except Exception as e:
            status_callback(f"Error loading PostgreSQL schemas: {e}", 5000)
            if self.pg_conn:
                self.pg_conn.close()
            self.pg_conn = None


    def load_tables_on_expand(self, index: QModelIndex, schema_model, status_callback):
        item = schema_model.itemFromIndex(index)
        if not item or (item.rowCount() > 0 and item.child(0).text() != "Loading..."):
            return # Already loaded or not a schema item to expand

        item.removeRows(0, item.rowCount()) # Clear the "Loading..." placeholder

        item_data = item.data(Qt.ItemDataRole.UserRole)
        schema_name = item_data.get('schema_name')
        if not self.pg_conn: # Reconnect if connection was closed or failed
            try:
                self.pg_conn = self.connect(item_data.get('conn_data'))
            except Exception as e:
                status_callback(f"Error reconnecting for schema expansion: {e}", 5000)
                return

        try:
            cursor = self.pg_conn.cursor()
            cursor.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY table_type, table_name;", (schema_name,))
            tables = cursor.fetchall()
            for (table_name, table_type) in tables:
                icon_path = "assets/table_icon.png" if "TABLE" in table_type else "assets/view_icon.png"
                table_item = QStandardItem(QIcon(icon_path), table_name)
                table_item.setEditable(False)
                # Pass the original conn_data and schema_name to the table item for query tool
                table_item_data = item_data.copy()
                table_item.setData(table_item_data, Qt.ItemDataRole.UserRole)
                item.appendRow(table_item)
        except Exception as e:
            status_callback(f"Error expanding schema '{schema_name}': {e}", 5000)
            # Re-add "Loading..." or show an error item if expansion failed
            item.appendRow(QStandardItem("Error loading tables."))
            # Consider closing the connection if it seems broken
            if self.pg_conn:
                self.pg_conn.close()
                self.pg_conn = None

    def get_connection_dialog(self, parent=None, conn_data=None, is_editing=False):
        dialog = PostgresConnectionDialog(parent, is_editing)
        if is_editing and conn_data:
            dialog.name_input.setText(conn_data.get("name", ""))
            dialog.host_input.setText(conn_data.get("host", ""))
            dialog.port_input.setText(str(conn_data.get("port", "")))
            dialog.db_input.setText(conn_data.get("database", ""))
            dialog.user_input.setText(conn_data.get("user", ""))
            dialog.password_input.setText(conn_data.get("password", ""))
        return dialog