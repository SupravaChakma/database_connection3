# db_connections.py
from abc import ABC, abstractmethod

class DBConnector(ABC):
    @abstractmethod
    def connect(self, conn_data):
        """Establishes a connection to the database."""
        pass

    @abstractmethod
    def close(self, conn):
        """Closes the database connection."""
        pass

    @abstractmethod
    def execute_query(self, conn, query):
        """Executes a query and returns results, columns, row count, etc."""
        pass

    @abstractmethod
    def load_schema(self, conn_data):
        """Loads the database schema (tables, views, etc.)."""
        pass

    @abstractmethod
    def get_connection_dialog(self, parent=None, conn_data=None, is_editing=False):
        """Returns the appropriate connection dialog for the database type."""
        pass