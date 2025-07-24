# database_manager.py
import sqlite3 as sqlite
import datetime
import os

class DatabaseManager:
    def __init__(self, db_file='hierarchy.db'):
        self.db_file = db_file
        self._initialize_db()

    def _initialize_db(self):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()

        # Schema Setup and Migration
        c.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
        c.execute("CREATE TABLE IF NOT EXISTS subcategories (id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER, FOREIGN KEY (category_id) REFERENCES categories (id))")
        c.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT, subcategory_id INTEGER, host TEXT, \"database\" TEXT, \"user\" TEXT, password TEXT, port INTEGER, db_path TEXT, FOREIGN KEY (subcategory_id) REFERENCES subcategories (id))")

        c.execute("SELECT COUNT(*) FROM categories")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO categories (name) VALUES ('PostgreSQL Connections'), ('SQLite Connections')")

        c.execute("PRAGMA table_info(items)")
        if 'usage_count' not in [col[1] for col in c.fetchall()]:
            c.execute("ALTER TABLE items ADD COLUMN usage_count INTEGER NOT NULL DEFAULT 0")

        c.execute("CREATE TABLE IF NOT EXISTS query_history (id INTEGER PRIMARY KEY, query_text TEXT, timestamp TEXT)")

        # Add missing columns to query_history for backward compatibility
        c.execute("PRAGMA table_info(query_history)")
        history_columns = [col[1] for col in c.fetchall()]
        if 'connection_item_id' not in history_columns:
            c.execute("ALTER TABLE query_history ADD COLUMN connection_item_id INTEGER NOT NULL DEFAULT -1")
        if 'status' not in history_columns:
            c.execute("ALTER TABLE query_history ADD COLUMN status TEXT NOT NULL DEFAULT 'Unknown'")
        if 'rows_affected' not in history_columns:
            c.execute("ALTER TABLE query_history ADD COLUMN rows_affected INTEGER")
        if 'execution_time_sec' not in history_columns:
            c.execute("ALTER TABLE query_history ADD COLUMN execution_time_sec REAL")

        conn.commit()
        conn.close()

    def get_all_connections_hierarchy(self):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        
        categories_data = []
        c.execute("SELECT id, name FROM categories")
        categories = c.fetchall()
        
        for cat_id, cat_name in categories:
            cat_item_data = {"id": cat_id, "name": cat_name, "subcategories": []}
            
            c.execute("SELECT id, name FROM subcategories WHERE category_id=?", (cat_id,))
            subcats = c.fetchall()
            
            for subcat_id, subcat_name in subcats:
                subcat_item_data = {"id": subcat_id, "name": subcat_name, "items": []}
                
                c.execute("SELECT id, name, host, \"database\", \"user\", password, port, db_path, usage_count FROM items WHERE subcategory_id=?", (subcat_id,))
                items = c.fetchall()
                
                for item_row in items:
                    item_id, name, host, db, user, pwd, port, db_path, usage_count = item_row
                    conn_data = {
                        "id": item_id, "name": name, "host": host, "database": db,
                        "user": user, "password": pwd, "port": port, "db_path": db_path,
                        "usage_count": usage_count
                    }
                    subcat_item_data["items"].append(conn_data)
                cat_item_data["subcategories"].append(subcat_item_data)
            categories_data.append(cat_item_data)
        
        conn.close()
        return categories_data

    def get_all_joined_connections(self):
        conn = sqlite.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.name, sc.name, i.name, i.host, i.database, i.user, i.password, i.port, i.db_path, i.id, i.usage_count 
            FROM categories c 
            JOIN subcategories sc ON sc.category_id = c.id 
            JOIN items i ON i.subcategory_id = sc.id 
            ORDER BY i.usage_count DESC, c.name, sc.name, i.name
        """)
        all_items = cursor.fetchall()
        conn.close()
        
        formatted_items = []
        for row in all_items:
            cat_name, subcat_name, item_name, host, db, user, pwd, port, db_path, item_id, usage_count = row
            conn_data = {
                "id": item_id, "name": item_name, "host": host, "database": db,
                "user": user, "password": pwd, "port": port, "db_path": db_path,
                "usage_count": usage_count
            }
            formatted_items.append((cat_name, subcat_name, item_name, conn_data))
        return formatted_items

    def add_subcategory(self, category_id, name):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("INSERT INTO subcategories (name, category_id) VALUES (?, ?)", (name, category_id))
        conn.commit()
        conn.close()

    def add_connection(self, subcategory_id, data):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        if "db_path" in data: # SQLite
            c.execute("INSERT INTO items (name, subcategory_id, db_path) VALUES (?, ?, ?)",
                      (data["name"], subcategory_id, data["db_path"]))
        else: # PostgreSQL
            c.execute("INSERT INTO items (name, subcategory_id, host, \"database\", \"user\", password, port) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (data["name"], subcategory_id, data["host"], data["database"], data["user"], data["password"], data["port"]))
        conn.commit()
        conn.close()

    def update_connection(self, item_id, data):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        if "db_path" in data: # SQLite
            c.execute("UPDATE items SET name = ?, db_path = ? WHERE id = ?",
                      (data["name"], data["db_path"], item_id))
        else: # PostgreSQL
            c.execute("UPDATE items SET name = ?, host = ?, database = ?, user = ?, password = ?, port = ? WHERE id = ?",
                      (data["name"], data["host"], data["database"], data["user"], data["password"], data["port"], item_id))
        conn.commit()
        conn.close()
    
    def increment_usage_count(self, item_id):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("UPDATE items SET usage_count = usage_count + 1 WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()

    def delete_connection(self, item_id):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("DELETE FROM items WHERE id = ?", (item_id,))
        c.execute("DELETE FROM query_history WHERE connection_item_id = ?", (item_id,))
        conn.commit()
        conn.close()

    def save_query_to_history(self, conn_id, query, status, rows, duration):
        if not conn_id: return
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("INSERT INTO query_history (connection_item_id, query_text, status, rows_affected, execution_time_sec, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                  (conn_id, query, status, rows, duration, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def get_connection_history(self, conn_id):
        if not conn_id: return []
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("SELECT id, query_text, timestamp, status, rows_affected, execution_time_sec FROM query_history WHERE connection_item_id = ? ORDER BY timestamp DESC", (conn_id,))
        history = c.fetchall()
        conn.close()
        
        formatted_history = []
        for row in history:
            history_id, query, ts, status, rows, duration = row
            dt = datetime.datetime.fromisoformat(ts)
            formatted_history.append({
                "id": history_id,
                "query": query,
                "timestamp": dt.strftime('%Y-%m-%d %H:%M:%S'),
                "status": status,
                "rows": rows,
                "duration": duration
            })
        return formatted_history

    def remove_history_item(self, history_id):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("DELETE FROM query_history WHERE id = ?", (history_id,))
        conn.commit()
        conn.close()

    def remove_all_history_for_connection(self, conn_id):
        conn = sqlite.connect(self.db_file)
        c = conn.cursor()
        c.execute("DELETE FROM query_history WHERE connection_item_id = ?", (conn_id,))
        conn.commit()
        conn.close()