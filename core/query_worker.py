# query_worker.py
import time
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QRunnable
import psycopg2
import sqlite3 as sqlite

# --- Signals class for QRunnable worker ---
class QuerySignals(QObject):
    finished = pyqtSignal(dict, str, list, list, int, float, bool)
    error = pyqtSignal(str)


# --- Worker now inherits from QRunnable for use with QThreadPool ---
class RunnableQuery(QRunnable):
    def __init__(self, conn_data, query, signals):
        super().__init__()
        self.conn_data = conn_data
        self.query = query
        self.signals = signals
        self._is_cancelled = False
        self.conn = None # To hold the connection object

    def cancel(self):
        self._is_cancelled = True
        # Attempt to close the connection if it's open
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                print(f"Error closing connection during cancel: {e}")

    def run(self):
        try:
            start_time = time.time()
            if not self.conn_data:
                raise ConnectionError("Incomplete connection information.")

            # Determine connection type and establish connection
            if "db_path" in self.conn_data and self.conn_data["db_path"]:
                self.conn = sqlite.connect(self.conn_data["db_path"])
            else:
                self.conn = psycopg2.connect(
                    host=self.conn_data["host"], database=self.conn_data["database"],
                    user=self.conn_data["user"], password=self.conn_data["password"],
                    port=int(self.conn_data["port"])
                )

            cursor = self.conn.cursor()
            cursor.execute(self.query)

            if self._is_cancelled:
                self.conn.close()
                return

            row_count = 0
            is_select_query = self.query.lower().strip().startswith("select")
            results = []
            columns = []

            if is_select_query:
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    if not self._is_cancelled:
                        results = cursor.fetchall()
                        row_count = len(results)
                else:
                    row_count = 0
            else:
                self.conn.commit()
                row_count = cursor.rowcount if cursor.rowcount != -1 else 0

            if self._is_cancelled:
                self.conn.close()
                return

            elapsed_time = time.time() - start_time
            self.signals.finished.emit(
                self.conn_data, self.query, results, columns, row_count, elapsed_time, is_select_query)

        except Exception as e:
            if not self._is_cancelled:
                self.signals.error.emit(str(e))
        finally:
            if self.conn:
                self.conn.close()