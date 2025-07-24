import sys
import os
import time
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QTabWidget,
    QSplitter, QTextEdit, QComboBox, QTableView, QVBoxLayout, QWidget, QStatusBar, QToolBar,
    QSizePolicy, QPushButton, QInputDialog, QMessageBox, QMenu, QAbstractItemView, QDialog,
    QHBoxLayout, QStackedWidget, QLabel, QGroupBox
)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QStandardItemModel, QStandardItem, QFont, QMovie
from PyQt6.QtCore import Qt, QDir, QModelIndex, QSize, QObject, pyqtSignal, QRunnable, QThreadPool, QTimer

# Import refactored modules
from core.query_worker import QuerySignals, RunnableQuery
from core.db_manager import DatabaseManager
from core.sqlite_connector import SQLiteConnector
from core.postgres_connector import PostgresConnector
from dialogs.confirmation_dialogs import show_info_dialog, show_warning_dialog, show_critical_dialog, show_question_dialog
from dialogs.connection_dialog import ConnectionDialog


class MainWindow(QMainWindow):
    QUERY_TIMEOUT = 60000

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SQL Client")
        self.setGeometry(100, 100, 1200, 800)

        self.db_manager = DatabaseManager()
        self.sqlite_connector = SQLiteConnector()
        self.postgres_connector = PostgresConnector()
        # self.oracle_connector = OracleConnector() # Initialize if implemented

        self.thread_pool = QThreadPool.globalInstance()
        self.tab_timers = {}
        self.running_queries = {}
        self.active_schema_connector = None # To hold the currently active connector for schema Browse

        self._create_actions()
        self._create_menu()
        self._create_centered_toolbar()

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_message_label = QLabel("Ready")
        self.status.addWidget(self.status_message_label)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeView()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.clicked.connect(self.item_clicked)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(['Object Explorer'])
        self.tree.setModel(self.model)

        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        vertical_splitter.addWidget(self.tree)

        self.schema_tree = QTreeView()
        self.schema_model = QStandardItemModel()
        self.schema_model.setHorizontalHeaderLabels(["Database Schema"])
        self.schema_tree.setModel(self.schema_model)
        self.schema_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.schema_tree.customContextMenuRequested.connect(
            self.show_schema_context_menu)
        
        # Connect schema tree expanded signal once
        self.schema_tree.expanded.connect(self._handle_schema_tree_expansion)

        vertical_splitter.addWidget(self.schema_tree)

        vertical_splitter.setSizes([240, 360])
        left_layout.addWidget(vertical_splitter)
        main_splitter.addWidget(left_panel)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        add_tab_btn = QPushButton("New")
        add_tab_btn.clicked.connect(self.add_tab)
        self.tab_widget.setCornerWidget(add_tab_btn)
        main_splitter.addWidget(self.tab_widget)

        self.thread_monitor_timer = QTimer()
        self.thread_monitor_timer.timeout.connect(self.update_thread_pool_status)
        self.thread_monitor_timer.start(1000)

        self.load_object_explorer_data()
        self.add_tab()
        main_splitter.setSizes([280, 920])
        self._apply_styles()

    def _create_actions(self):
        """Creates all QAction objects for menus and toolbars."""
        # --- File Menu Actions ---
        self.preferences_action = QAction("Preferences", self)
        self.preferences_action.triggered.connect(self.show_preferences)
        self.reset_layout_action = QAction("Reset Layout", self)
        self.reset_layout_action.triggered.connect(self.reset_layout)
        self.view_logs_action = QAction("View Logs...", self)
        self.view_logs_action.triggered.connect(self.view_logs)
        self.configure_runtime_action = QAction("Configure runtime...", self)
        self.configure_runtime_action.triggered.connect(self.configure_runtime)
        self.exit_action = QAction(QIcon("assets/exit_icon.png"), "Exit", self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu_exit_action = QAction("Exit", self) # For the File menu (no icon)
        self.file_menu_exit_action.triggered.connect(self.close)

        # --- Edit Menu Actions ---
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo_text)
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo_text)
        self.cut_action = QAction("Cut", self)
        self.cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        self.cut_action.triggered.connect(self.cut_text)
        self.copy_action = QAction("Copy", self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self.copy_text)
        self.paste_action = QAction("Paste", self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.paste_text)
        self.find_action = QAction("Find", self)
        self.find_action.setShortcut("Ctrl+F")
        self.find_action.triggered.connect(self.find_text)

        # --- Tools Menu Actions ---
        self.erd_tool_action = QAction("ERD Tool", self)
        self.erd_tool_action.triggered.connect(self.not_implemented)
        self.grant_wizard_action = QAction("Grant Wizard...", self)
        self.grant_wizard_action.triggered.connect(self.not_implemented)
        self.psql_tool_action = QAction("PSQL Tool", self)
        self.psql_tool_action.triggered.connect(self.not_implemented)
        self.query_tool_action = QAction("Query Tool", self)
        self.query_tool_action.triggered.connect(self.add_tab)
        self.schema_diff_action = QAction("Schema Diff", self)
        self.schema_diff_action.triggered.connect(self.not_implemented)
        self.restore_action = QAction("Restore...", self)
        self.restore_action.triggered.connect(self.not_implemented)
        self.backup_globals_action = QAction("Backup Globals...", self)
        self.backup_globals_action.triggered.connect(self.not_implemented)
        self.backup_server_action = QAction("Backup Server...", self)
        self.backup_server_action.triggered.connect(self.not_implemented)
        self.backup_action = QAction("Backup...", self)
        self.backup_action.triggered.connect(self.not_implemented)
        self.import_export_data_action = QAction("Import/Export Data...", self)
        self.import_export_data_action.triggered.connect(self.not_implemented)
        self.import_export_servers_action = QAction("Import/Export Servers...", self)
        self.import_export_servers_action.triggered.connect(self.not_implemented)
        self.maintenance_action = QAction("Maintenance...", self)
        self.maintenance_action.triggered.connect(self.not_implemented)
        self.search_objects_action = QAction("Search Objects...", self)
        self.search_objects_action.triggered.connect(self.not_implemented)

        # --- View Menu Actions ---
        self.reload_action = QAction("Reload", self)
        self.reload_action.triggered.connect(self.not_implemented)
        self.toggle_dev_tools_action = QAction("Toggle Developer Tools", self)
        self.toggle_dev_tools_action.triggered.connect(self.not_implemented)
        self.actual_size_action = QAction("Actual Size", self)
        self.actual_size_action.setShortcut("Ctrl+0")
        self.actual_size_action.triggered.connect(self.not_implemented)
        self.zoom_in_action = QAction("Zoom In", self)
        self.zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.zoom_in_action.triggered.connect(self.not_implemented)
        self.zoom_out_action = QAction("Zoom Out", self)
        self.zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.zoom_out_action.triggered.connect(self.not_implemented)
        self.toggle_full_screen_action = QAction("Toggle Full Screen", self)
        self.toggle_full_screen_action.setShortcut("F11")
        self.toggle_full_screen_action.triggered.connect(self.toggle_fullscreen)

        # --- Toolbar Actions ---
        self.execute_action = QAction(QIcon("assets/execute_icon.png"), "Execute", self)
        self.execute_action.triggered.connect(self.execute_query)
        self.cancel_action = QAction(QIcon("assets/cancel_icon.png"), "Cancel", self)
        self.cancel_action.triggered.connect(self.cancel_current_query)
        self.cancel_action.setEnabled(False)

    def _create_menu(self):
        """Creates the main menubar and populates it with actions."""
        menubar = self.menuBar()

        # --- File Menu ---
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.preferences_action)
        file_menu.addAction(self.reset_layout_action)
        file_menu.addSeparator()
        file_menu.addAction(self.view_logs_action)
        file_menu.addAction(self.configure_runtime_action)
        file_menu.addSeparator()
        file_menu.addAction(self.file_menu_exit_action)

        # --- Object Menu ---
        object_menu = menubar.addMenu("&Object")
        object_menu.addAction(QAction("Count Rows", self, triggered=self.not_implemented))
        create_submenu = QMenu("Create", self)
        create_submenu.addAction(QAction("Table...", self, triggered=self.not_implemented))
        create_submenu.addAction(QAction("View...", self, triggered=self.not_implemented))
        object_menu.addMenu(create_submenu)
        object_menu.addSeparator()
        object_menu.addAction(QAction("Delete", self, triggered=self.not_implemented))
        object_menu.addAction(QAction("Delete (Cascade)", self, triggered=self.not_implemented))
        object_menu.addAction(QAction("Refresh...", self, triggered=self.not_implemented))
        object_menu.addAction(QAction("Reset Statistics", self, triggered=self.not_implemented))
        object_menu.addAction(QAction("ERD For Table", self, triggered=self.not_implemented))
        scripts_submenu = QMenu("Scripts", self)
        scripts_submenu.addAction(QAction("CREATE Script", self, triggered=self.not_implemented))
        scripts_submenu.addAction(QAction("SELECT Script", self, triggered=self.not_implemented))
        scripts_submenu.addAction(QAction("INSERT Script", self, triggered=self.not_implemented))
        scripts_submenu.addAction(QAction("UPDATE Script", self, triggered=self.not_implemented))
        scripts_submenu.addAction(QAction("DELETE Script", self, triggered=self.not_implemented))
        object_menu.addMenu(scripts_submenu)
        triggers_submenu = QMenu("Trigger(s)", self)
        triggers_submenu.addAction(QAction("Create Trigger...", self, triggered=self.not_implemented))
        object_menu.addMenu(triggers_submenu)
        truncate_submenu = QMenu("Truncate", self)
        truncate_submenu.addAction(QAction("Truncate", self, triggered=self.not_implemented))
        truncate_submenu.addAction(QAction("Truncate (Cascade)", self, triggered=self.not_implemented))
        object_menu.addMenu(truncate_submenu)
        view_edit_submenu = QMenu("View/Edit Data", self)
        view_edit_submenu.addAction(QAction("All Rows", self, triggered=self.not_implemented))
        view_edit_submenu.addAction(QAction("First 100 Rows", self, triggered=self.not_implemented))
        view_edit_submenu.addAction(QAction("Filtered Rows...", self, triggered=self.not_implemented))
        object_menu.addMenu(view_edit_submenu)
        object_menu.addAction(QAction("Properties...", self, triggered=self.not_implemented))

        # --- Tools Menu ---
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(self.erd_tool_action)
        tools_menu.addAction(self.grant_wizard_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.psql_tool_action)
        tools_menu.addAction(self.query_tool_action)
        tools_menu.addAction(self.schema_diff_action)
        tools_menu.addSeparator()
        server_submenu = QMenu("Server", self)
        server_submenu.addAction("Connect to Server...").triggered.connect(self.not_implemented)
        server_submenu.addAction("Disconnect from Server").triggered.connect(self.not_implemented)
        tools_menu.addMenu(server_submenu)
        tools_menu.addAction(self.restore_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.backup_globals_action)
        tools_menu.addAction(self.backup_server_action)
        tools_menu.addAction(self.backup_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.import_export_data_action)
        tools_menu.addAction(self.import_export_servers_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.maintenance_action)
        tools_menu.addAction(self.search_objects_action)

        # --- Edit Menu ---
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.cut_action)
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.find_action)

        # --- View Menu ---
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.reload_action)
        view_menu.addAction(self.toggle_dev_tools_action)
        view_menu.addSeparator()
        view_menu.addAction(self.actual_size_action)
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_full_screen_action)

        # --- Window Menu ---
        window_menu = menubar.addMenu("&Window")
        minimize_action = QAction("Minimize", self)
        minimize_action.setShortcut("Ctrl+M")
        minimize_action.triggered.connect(self.showMinimized) # Built-in slot
        window_menu.addAction(minimize_action)

        zoom_action = QAction("Zoom", self)
        zoom_action.triggered.connect(self.not_implemented) # Placeholder
        window_menu.addAction(zoom_action)

        close_action = QAction("Close", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(self.close) # Built-in slot to close the app
        window_menu.addAction(close_action)

        # --- Help Menu ---
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(QAction("Quick Search", self, triggered=self.not_implemented))
        help_menu.addAction(QAction("Online Help", self, triggered=self.not_implemented))
        help_menu.addAction(QAction("pgAdmin Website", self, triggered=self.not_implemented))
        help_menu.addAction(QAction("PostgreSQL Website", self, triggered=self.not_implemented))
        about_action = QAction("About pgAdmin 4", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def _create_centered_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        left_spacer = QWidget()
        left_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        right_spacer = QWidget()
        right_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(left_spacer)
        toolbar.addAction(self.exit_action)
        toolbar.addAction(self.execute_action)
        toolbar.addAction(self.cancel_action)
        toolbar.addWidget(right_spacer)
        self.addToolBar(toolbar)

    def update_thread_pool_status(self):
         active = self.thread_pool.activeThreadCount()
         max_threads = self.thread_pool.maxThreadCount()
         self.status.showMessage(f"ThreadPool: {active} active of {max_threads}", 3000)

    def _apply_styles(self):
        style_sheet= """
            QTableView {
                alternate-background-color: #f5f5f5;
                background-color: white;
                gridline-color: #d0d0d0;
                border: 1px solid #c0c0c0;
                font-family: Arial, sans-serif;
                font-size: 9pt;
            }
            QTableView::item { padding: 4px; }
            QTableView::item:selected { background-color: #5698d4; color: white; }
            QHeaderView::section {
                background-color: #464646;
                color: white;
                padding: 6px;
                border: 1px solid #2a436e;
                font-weight: bold;
                font-size: 9pt;
            }
            QTableView QTableCornerButton::section {
                background-color: #464646;
                border: 1px solid #2a436e;
            }
        """
        self.setStyleSheet(style_sheet)

    def add_tab(self):
        tab_content = QWidget(self.tab_widget)
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        db_combo_box = QComboBox()
        db_combo_box.setObjectName("db_combo_box")
        layout.addWidget(db_combo_box)
        self.load_joined_items(db_combo_box)

        main_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(main_vertical_splitter)

        # --- Top Part: Editor / History ---
        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0,0,0,0)
        editor_layout.setSpacing(0)

        editor_header = QWidget()
        editor_header.setObjectName("editorHeader")
        editor_header_layout = QHBoxLayout(editor_header)
        editor_header_layout.setContentsMargins(5, 2, 5, 0)
        editor_header_layout.setSpacing(2)

        query_view_btn = QPushButton("Query")
        history_view_btn = QPushButton("Query History")
        query_view_btn.setCheckable(True)
        history_view_btn.setCheckable(True)
        query_view_btn.setChecked(True)
        editor_header_layout.addWidget(query_view_btn)
        editor_header_layout.addWidget(history_view_btn)
        editor_header_layout.addStretch()
        editor_layout.addWidget(editor_header)

        editor_stack = QStackedWidget()
        editor_stack.setObjectName("editor_stack")

        # Page 0: Query Editor
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("Write your SQL query here...")
        text_edit.setObjectName("query_editor")
        editor_stack.addWidget(text_edit)

        # Page 1: History View
        history_widget = QSplitter(Qt.Orientation.Horizontal)
        history_list_view = QTreeView()
        history_list_view.setObjectName("history_list_view")
        history_list_view.setHeaderHidden(True)
        history_list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        history_details_group = QGroupBox("Query Details")
        history_details_layout = QVBoxLayout(history_details_group)
        history_details_view = QTextEdit()
        history_details_view.setObjectName("history_details_view")
        history_details_view.setReadOnly(True)
        history_details_layout.addWidget(history_details_view)

        history_button_layout = QHBoxLayout()
        copy_history_btn = QPushButton("Copy")
        copy_to_edit_btn = QPushButton("Copy to Edit Query")
        remove_history_btn = QPushButton("Remove")
        remove_all_history_btn = QPushButton("Remove All")
        
        history_button_layout.addStretch()
        history_button_layout.addWidget(copy_history_btn)
        history_button_layout.addWidget(copy_to_edit_btn)
        history_button_layout.addWidget(remove_history_btn)
        history_button_layout.addWidget(remove_all_history_btn)
        history_details_layout.addLayout(history_button_layout)

        history_widget.addWidget(history_list_view)
        history_widget.addWidget(history_details_group)
        history_widget.setSizes([400, 400])
        editor_stack.addWidget(history_widget)

        editor_layout.addWidget(editor_stack)
        main_vertical_splitter.addWidget(editor_container)

        def switch_editor_view(index):
            editor_stack.setCurrentIndex(index)
            query_view_btn.setChecked(index == 0)
            history_view_btn.setChecked(index == 1)
            if index == 1:
                self.load_connection_history(tab_content)

        query_view_btn.clicked.connect(lambda: switch_editor_view(0))
        history_view_btn.clicked.connect(lambda: switch_editor_view(1))

        db_combo_box.currentIndexChanged.connect(lambda: editor_stack.currentIndex() == 1 and self.load_connection_history(tab_content))
        history_list_view.clicked.connect(lambda index: self.display_history_details(index, tab_content))
        
        # --- Connect new history buttons ---
        copy_history_btn.clicked.connect(lambda: self.copy_history_query(tab_content))
        copy_to_edit_btn.clicked.connect(lambda: self.copy_history_to_editor(tab_content))
        remove_history_btn.clicked.connect(lambda: self.remove_selected_history(tab_content))
        remove_all_history_btn.clicked.connect(lambda: self.remove_all_history_for_connection(tab_content))

        # --- Bottom Part: Results ---
        results_container = QWidget()
        results_layout = QVBoxLayout(results_container)
        results_layout.setContentsMargins(0, 5, 0, 0)
        results_layout.setSpacing(0)

        results_header = QWidget()
        results_header.setObjectName("resultsHeader")
        header_layout = QHBoxLayout(results_header)
        header_layout.setContentsMargins(5, 2, 5, 0)
        header_layout.setSpacing(2)

        output_btn = QPushButton("Output")
        message_btn = QPushButton("Message")
        notification_btn = QPushButton("Notification")

        output_btn.setCheckable(True)
        message_btn.setCheckable(True)
        notification_btn.setCheckable(True)
        output_btn.setChecked(True)

        header_layout.addWidget(output_btn)
        header_layout.addWidget(message_btn)
        header_layout.addWidget(notification_btn)
        header_layout.addStretch()

        results_layout.addWidget(results_header)

        results_stack = QStackedWidget()
        results_stack.setObjectName("results_stacked_widget")

        table_view = QTableView()
        table_view.setObjectName("result_table")
        table_view.setAlternatingRowColors(True)
        results_stack.addWidget(table_view)

        message_view = QTextEdit()
        message_view.setObjectName("message_view")
        message_view.setReadOnly(True)
        results_stack.addWidget(message_view)

        notification_view = QLabel("Notifications will appear here.")
        notification_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_stack.addWidget(notification_view)

        # --- Spinner View (Page 3) ---
        spinner_overlay_widget = QWidget()
        spinner_layout = QHBoxLayout(spinner_overlay_widget)
        spinner_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spinner_movie = QMovie("assets/spinner.gif")
        spinner_label = QLabel()
        spinner_label.setObjectName("spinner_label")

        if not spinner_movie.isValid():
            spinner_label.setText("Loading...") # Fallback text
        else:
            spinner_label.setMovie(spinner_movie)
            spinner_movie.setScaledSize(QSize(32, 32))

        loading_text_label = QLabel("Waiting for query to complete...")
        font = QFont()
        font.setPointSize(10)
        loading_text_label.setFont(font)
        loading_text_label.setStyleSheet("color: #555;")
        spinner_layout.addWidget(spinner_label)
        spinner_layout.addWidget(loading_text_label)
        results_stack.addWidget(spinner_overlay_widget)

        results_layout.addWidget(results_stack)

        tab_status_label = QLabel("Ready")
        tab_status_label.setObjectName("tab_status_label")
        results_layout.addWidget(tab_status_label)

        button_group = [output_btn, message_btn, notification_btn]
        def switch_results_view(index):
            if results_stack.currentIndex() != 3:
                results_stack.setCurrentIndex(index)
                for i, btn in enumerate(button_group):
                    btn.setChecked(i == index)

        output_btn.clicked.connect(lambda: switch_results_view(0))
        message_btn.clicked.connect(lambda: switch_results_view(1))
        notification_btn.clicked.connect(lambda: switch_results_view(2))

        main_vertical_splitter.addWidget(results_container)
        main_vertical_splitter.setSizes([300, 300])

        tab_content.setLayout(layout)
        index = self.tab_widget.addTab(
            tab_content, f"Worksheet {self.tab_widget.count() + 1}")
        self.tab_widget.setCurrentIndex(index)
        self.renumber_tabs()
        return tab_content

    def close_tab(self, index):
        tab = self.tab_widget.widget(index)
        if tab in self.running_queries:
            self.running_queries[tab].cancel()
            del self.running_queries[tab]
            if not self.running_queries:
                self.cancel_action.setEnabled(False)
        if tab in self.tab_timers:
            self.tab_timers[tab]["timer"].stop()
            if "timeout_timer" in self.tab_timers[tab]:
                self.tab_timers[tab]["timeout_timer"].stop()
            del self.tab_timers[tab]
        if self.tab_widget.count() > 1:
            self.tab_widget.removeTab(index)
            self.renumber_tabs()
        else:
            self.status.showMessage("Must keep at least one tab", 3000)

    def renumber_tabs(self):
        for i in range(self.tab_widget.count()):
            self.tab_widget.setTabText(i, f"Worksheet {i + 1}")

    def load_object_explorer_data(self):
        self.model.clear()
        self.model.setHorizontalHeaderLabels(["Object Explorer"])
        categories_data = self.db_manager.get_all_connections_hierarchy()
        
        for cat_data in categories_data:
            cat_item = QStandardItem(cat_data["name"])
            cat_item.setData(cat_data["id"], Qt.ItemDataRole.UserRole + 1) # Store category ID
            
            for subcat_data in cat_data["subcategories"]:
                subcat_item = QStandardItem(subcat_data["name"])
                subcat_item.setData(subcat_data["id"], Qt.ItemDataRole.UserRole + 1) # Store subcategory ID
                
                for item_data in subcat_data["items"]:
                    item_item = QStandardItem(item_data["name"])
                    item_item.setData(item_data, Qt.ItemDataRole.UserRole) # Store full connection data
                    subcat_item.appendRow(item_item)
                cat_item.appendRow(subcat_item)
            self.model.appendRow(cat_item)

    def item_clicked(self, index):
        item = self.model.itemFromIndex(index)
        depth = self.get_item_depth(item)
        self.schema_model.clear()
        self.schema_model.setHorizontalHeaderLabels(["Database Schema"])
        
        # Disconnect previous expansion handler to avoid multiple connections if changing DB type
        try: self.schema_tree.expanded.disconnect(self._handle_schema_tree_expansion)
        except TypeError: pass # Ignore if not connected

        if depth == 3: # Connection item clicked
            conn_data = item.data(Qt.ItemDataRole.UserRole)
            if conn_data:
                self.status.showMessage(f"Loading schema for {conn_data.get('name')}...", 3000)
                
                # Determine the correct connector and load schema
                if conn_data.get("host"): # PostgreSQL
                    self.active_schema_connector = self.postgres_connector
                    self.postgres_connector.load_schema(
                        conn_data, self.schema_model, self.status.showMessage,
                        lambda handler: self.schema_tree.expanded.connect(partial(handler, schema_model=self.schema_model, status_callback=self.status.showMessage))
                    )
                elif conn_data.get("db_path"): # SQLite
                    self.active_schema_connector = self.sqlite_connector
                    self.sqlite_connector.load_schema(
                        conn_data, self.schema_model, self.status.showMessage
                    )
        # Reconnect the main schema expansion handler
        self.schema_tree.expanded.connect(self._handle_schema_tree_expansion)


    def _handle_schema_tree_expansion(self, index: QModelIndex):
        """Generic handler for schema tree expansion, delegates to active connector."""
        if self.active_schema_connector and hasattr(self.active_schema_connector, 'load_tables_on_expand'):
            self.active_schema_connector.load_tables_on_expand(index, self.schema_model, self.status.showMessage)


    def get_item_depth(self, item):
        depth = 0
        parent = item.parent()
        while parent is not None:
            depth += 1
            parent = parent.parent()
        return depth + 1

    def show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid(): return
        item = self.model.itemFromIndex(index)
        depth = self.get_item_depth(item)
        menu = QMenu()
        if depth == 1: # Category (e.g., PostgreSQL Connections)
            add_subcat = QAction("Add Group", self)
            add_subcat.triggered.connect(lambda: self.add_subcategory(item))
            menu.addAction(add_subcat)
        elif depth == 2: # Subcategory (e.g., Local PostgreSQL)
            parent_category_item = item.parent()
            if parent_category_item:
                category_name = parent_category_item.text()
                if "postgres" in category_name.lower():
                    add_pg_action = QAction("Add New PostgreSQL Connection", self)
                    add_pg_action.triggered.connect(lambda: self.add_connection_dialog(item, self.postgres_connector))
                    menu.addAction(add_pg_action)
                elif "sqlite" in category_name.lower():
                    add_sqlite_action = QAction("Add New SQLite Connection", self)
                    add_sqlite_action.triggered.connect(lambda: self.add_connection_dialog(item, self.sqlite_connector))
                    menu.addAction(add_sqlite_action)
        elif depth == 3: # Connection item
            conn_data = item.data(Qt.ItemDataRole.UserRole)
            if conn_data:
                edit_action = QAction("Edit Connection", self)
                edit_action.triggered.connect(lambda: self.edit_connection_dialog(item, conn_data))
                menu.addAction(edit_action)
                delete_action = QAction("Delete Connection", self)
                delete_action.triggered.connect(lambda: self.delete_connection_item(item))
                menu.addAction(delete_action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def add_subcategory(self, parent_item):
        name, ok = QInputDialog.getText(self, "New Group", "Group name:")
        if ok and name:
            try:
                category_id = parent_item.data(Qt.ItemDataRole.UserRole+1)
                self.db_manager.add_subcategory(category_id, name)
                self.load_object_explorer_data()
                self.refresh_all_comboboxes()
            except Exception as e:
                show_critical_dialog(self, "Error", f"Failed to add group:\n{e}")

    def add_connection_dialog(self, parent_item, connector):
        subcat_id = parent_item.data(Qt.ItemDataRole.UserRole + 1)
        dialog = connector.get_connection_dialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            try:
                self.db_manager.add_connection(subcat_id, data)
                self.load_object_explorer_data()
                self.refresh_all_comboboxes()
            except Exception as e:
                show_critical_dialog(self, "Error", f"Failed to save connection:\n{e}")

    def edit_connection_dialog(self, item, conn_data):
        connector = None
        if conn_data.get("db_path"): # SQLite
            connector = self.sqlite_connector
        elif conn_data.get("host"): # PostgreSQL
            connector = self.postgres_connector
        
        if not connector: return

        dialog = connector.get_connection_dialog(self, conn_data=conn_data, is_editing=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_data()
            try:
                self.db_manager.update_connection(conn_data["id"], new_data)
                self.load_object_explorer_data()
                self.refresh_all_comboboxes()
            except Exception as e:
                show_critical_dialog(self, "Error", f"Failed to update connection:\n{e}")

    def delete_connection_item(self, item):
        conn_data = item.data(Qt.ItemDataRole.UserRole)
        item_id = conn_data.get("id")
        if show_question_dialog(self, "Delete Connection", "Are you sure you want to delete this connection?"):
            try:
                self.db_manager.delete_connection(item_id)
                self.load_object_explorer_data()
                self.refresh_all_comboboxes()
            except Exception as e:
                show_critical_dialog(self, "Error", f"Failed to delete item:\n{e}")

    def refresh_all_comboboxes(self):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            combo_box = tab.findChild(QComboBox, "db_combo_box")
            if combo_box:
                self.load_joined_items(combo_box)

    def load_joined_items(self, combo_box):
        try:
            current_data_id = combo_box.currentData().get('id') if combo_box.currentData() else None
            combo_box.clear()
            all_items = self.db_manager.get_all_joined_connections()
            for cat_name, subcat_name, item_name, conn_data in all_items:
                visible_text = f"{cat_name} -> {subcat_name} -> {item_name}"
                combo_box.addItem(visible_text, conn_data)
            
            if current_data_id is not None:
                for i in range(combo_box.count()):
                    if combo_box.itemData(i) and combo_box.itemData(i)['id'] == current_data_id:
                        combo_box.setCurrentIndex(i)
                        break
        except Exception as e:
            self.status.showMessage(f"Error loading connections: {e}", 4000)

    def execute_query(self):
        current_tab = self.tab_widget.currentWidget()
        if not current_tab: return

        # Ensure editor_stack is found correctly
        editor_stack = current_tab.findChild(QStackedWidget, "editor_stack")
        if editor_stack is None:
            show_critical_dialog(self, "Internal Error", "Could not find the query editor stack.")
            return

        if editor_stack.currentIndex() == 1:
            show_info_dialog(self, "Info", "Cannot execute from History view. Switch to the Query view.")
            return

        if current_tab in self.running_queries:
            show_warning_dialog(self, "Query in Progress", "A query is already running in this tab.")
            return

        query_editor = current_tab.findChild(QTextEdit, "query_editor")
        db_combo_box = current_tab.findChild(QComboBox, "db_combo_box")

        index = db_combo_box.currentIndex()
        conn_data = db_combo_box.itemData(index)
        query = query_editor.toPlainText().strip()

        # --- NEW: Semicolon Check ---
        if not query.endswith(';'):
            show_warning_dialog(self, "Missing Semicolon", "Query must end with a semicolon (;) to execute.")
            self.status.showMessage("Execution aborted: Missing semicolon.", 3000)
            return
        # --- END NEW ---

        if not conn_data or not query:
            self.status.showMessage("Connection or query is empty", 3000)
            return

        results_stack = current_tab.findChild(QStackedWidget, "results_stacked_widget")
        spinner_label = results_stack.findChild(QLabel, "spinner_label")
        results_stack.setCurrentIndex(3)
        if spinner_label and spinner_label.movie():
            spinner_label.movie().start()

        tab_status_label = current_tab.findChild(QLabel, "tab_status_label")
        progress_timer = QTimer(self)
        start_time = time.time()
        timeout_timer = QTimer(self)
        timeout_timer.setSingleShot(True)
        self.tab_timers[current_tab] = {"timer": progress_timer, "start_time": start_time, "timeout_timer": timeout_timer}
        progress_timer.timeout.connect(partial(self.update_timer_label, tab_status_label, current_tab))
        progress_timer.start(100)
        signals = QuerySignals()
        runnable = RunnableQuery(conn_data, query, signals)
        signals.finished.connect(partial(self.handle_query_result, current_tab))
        signals.error.connect(partial(self.handle_query_error, current_tab))
        timeout_timer.timeout.connect(partial(self.handle_query_timeout, current_tab, runnable))
        self.running_queries[current_tab] = runnable
        self.cancel_action.setEnabled(True)
        self.thread_pool.start(runnable)
        timeout_timer.start(self.QUERY_TIMEOUT)
        self.status_message_label.setText("Executing query...")

    def update_timer_label(self, label, tab):
        if not label or tab not in self.tab_timers: return
        elapsed = time.time() - self.tab_timers[tab]["start_time"]
        label.setText(f"Running... {elapsed:.1f} sec")

    def handle_query_result(self, target_tab, conn_data, query, results, columns, row_count, elapsed_time, is_select_query):
        if target_tab in self.tab_timers:
            self.tab_timers[target_tab]["timer"].stop()
            self.tab_timers[target_tab]["timeout_timer"].stop()
            del self.tab_timers[target_tab]
        self.db_manager.save_query_to_history(conn_data.get("id"), query, "Success", row_count, elapsed_time)
        table_view = target_tab.findChild(QTableView, "result_table")
        message_view = target_tab.findChild(QTextEdit, "message_view")
        tab_status_label = target_tab.findChild(QLabel, "tab_status_label")
        if is_select_query:
            model = QStandardItemModel()
            model.setHorizontalHeaderLabels(columns)
            for row in results:
                model.appendRow([QStandardItem(str(cell)) for cell in row])
            table_view.setModel(model)
            msg = f"Query executed successfully.\n\nTotal rows: {row_count}\nTime: {elapsed_time:.2f} sec"
            status = f"Query executed successfully | Total rows: {row_count} | Time: {elapsed_time:.2f} sec"
        else:
            table_view.setModel(QStandardItemModel()) # Clear table view for non-select
            msg = f"Command executed successfully.\n\nRows affected: {row_count}\nTime: {elapsed_time:.2f} sec"
            status = f"Command executed successfully | Rows affected: {row_count} | Time: {elapsed_time:.2f} sec"
        message_view.setText(msg)
        tab_status_label.setText(status)
        self.status_message_label.setText("Ready")
        self.stop_spinner(target_tab, success=True)
        if target_tab in self.running_queries:
            del self.running_queries[target_tab]
        if not self.running_queries:
            self.cancel_action.setEnabled(False)

    def handle_query_error(self, target_tab, error_message):
        if target_tab in self.tab_timers:
            self.tab_timers[target_tab]["timer"].stop()
            self.tab_timers[target_tab]["timeout_timer"].stop()
            del self.tab_timers[target_tab]
        message_view = target_tab.findChild(QTextEdit, "message_view")
        tab_status_label = target_tab.findChild(QLabel, "tab_status_label")
        error_text = f"Error: {error_message}"
        message_view.setText(f"Error:\n\n{error_message}")
        tab_status_label.setText(error_text)
        self.db_manager.save_query_to_history(
            target_tab.findChild(QComboBox, "db_combo_box").currentData().get("id"), 
            target_tab.findChild(QTextEdit, "query_editor").toPlainText().strip(), 
            "Failed", 0, 0
        )
        self.status_message_label.setText("Error occurred")
        self.stop_spinner(target_tab, success=False)
        if target_tab in self.running_queries:
            del self.running_queries[target_tab]
        if not self.running_queries:
            self.cancel_action.setEnabled(False)

    def stop_spinner(self, target_tab, success=True):
        if not target_tab: return
        stacked_widget = target_tab.findChild(QStackedWidget, "results_stacked_widget")
        if stacked_widget:
            spinner_label = stacked_widget.findChild(QLabel, "spinner_label")
            if spinner_label and spinner_label.movie():
                spinner_label.movie().stop()
            header = target_tab.findChild(QWidget, "resultsHeader")
            buttons = header.findChildren(QPushButton)
            if success:
                stacked_widget.setCurrentIndex(0) # Show results table
                if buttons: buttons[0].setChecked(True); buttons[1].setChecked(False); buttons[2].setChecked(False)
            else:
                stacked_widget.setCurrentIndex(1) # Show message view
                if buttons: buttons[0].setChecked(False); buttons[1].setChecked(True); buttons[2].setChecked(False)

    def handle_query_timeout(self, tab, runnable):
        if self.running_queries.get(tab) is runnable:
            runnable.cancel()
            error_message = f"Error: Query Timed Out after {self.QUERY_TIMEOUT / 1000} seconds."
            tab.findChild(QTextEdit, "message_view").setText(error_message)
            tab.findChild(QLabel, "tab_status_label").setText(error_message)
            self.db_manager.save_query_to_history(
                tab.findChild(QComboBox, "db_combo_box").currentData().get("id"),
                tab.findChild(QTextEdit, "query_editor").toPlainText().strip(),
                "Timed Out", 0, self.QUERY_TIMEOUT / 1000
            )
            self.stop_spinner(tab, success=False)
            if tab in self.tab_timers:
                self.tab_timers[tab]["timer"].stop()
                del self.tab_timers[tab]
            if tab in self.running_queries:
                del self.running_queries[tab]
            if not self.running_queries:
                self.cancel_action.setEnabled(False)
            self.status_message_label.setText("Error occurred")
            show_warning_dialog(self, "Query Timeout", f"The query was stopped as it exceeded {self.QUERY_TIMEOUT / 1000}s.")

    def cancel_current_query(self):
        current_tab = self.tab_widget.currentWidget()
        runnable = self.running_queries.get(current_tab)
        if runnable:
            runnable.cancel()
            if current_tab in self.tab_timers:
                self.tab_timers[current_tab]["timer"].stop()
                self.tab_timers[current_tab]["timeout_timer"].stop()
                del self.tab_timers[current_tab]
            cancel_message = "Query cancelled by user."
            current_tab.findChild(QTextEdit, "message_view").setText(cancel_message)
            current_tab.findChild(QLabel, "tab_status_label").setText(cancel_message)
            self.db_manager.save_query_to_history(
                current_tab.findChild(QComboBox, "db_combo_box").currentData().get("id"),
                current_tab.findChild(QTextEdit, "query_editor").toPlainText().strip(),
                "Cancelled", 0, 0
            )
            self.stop_spinner(current_tab, success=False)
            self.status_message_label.setText("Query Cancelled")
            if current_tab in self.running_queries:
                del self.running_queries[current_tab]
            if not self.running_queries:
                self.cancel_action.setEnabled(False)

    # --- Query History Methods ---
    def load_connection_history(self, target_tab):
        history_list_view = target_tab.findChild(QTreeView, "history_list_view")
        history_details_view = target_tab.findChild(QTextEdit, "history_details_view")
        db_combo_box = target_tab.findChild(QComboBox, "db_combo_box")
        model = QStandardItemModel()
        history_list_view.setModel(model)
        history_details_view.clear()
        
        conn_data = db_combo_box.currentData()
        if not conn_data: 
            model.setHorizontalHeaderLabels(['No Connection Selected'])
            return
        
        model.setHorizontalHeaderLabels(['Connection History'])
        conn_id = conn_data.get("id")
        
        try:
            history = self.db_manager.get_connection_history(conn_id)
            for data in history:
                query = data['query']
                short_query = ' '.join(query.split())[:70] + ('...' if len(query) > 70 else '')
                display_text = f"{short_query}\n{data['timestamp']}"
                item = QStandardItem(display_text)
                item.setData(data, Qt.ItemDataRole.UserRole)
                model.appendRow(item)
        except Exception as e:
            show_critical_dialog(self, "Error", f"Failed to load query history:\n{e}")

    def display_history_details(self, index, target_tab):
        history_details_view = target_tab.findChild(QTextEdit, "history_details_view")
        if not index.isValid() or not history_details_view: return
        data = index.model().itemFromIndex(index).data(Qt.ItemDataRole.UserRole)
        details_text = f"Timestamp: {data['timestamp']}\nStatus: {data['status']}\nDuration: {data['duration']:.3f} sec\nRows: {data['rows']}\n\n-- Query --\n{data['query']}"
        history_details_view.setText(details_text)

    def _get_selected_history_item(self, target_tab):
        """Helper to get the selected item's data from the history list."""
        history_list_view = target_tab.findChild(QTreeView, "history_list_view")
        selected_indexes = history_list_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            show_info_dialog(self, "No Selection", "Please select a history item first.")
            return None
        item = selected_indexes[0].model().itemFromIndex(selected_indexes[0])
        return item.data(Qt.ItemDataRole.UserRole)

    def copy_history_query(self, target_tab):
        history_data = self._get_selected_history_item(target_tab)
        if history_data:
            clipboard = QApplication.clipboard()
            clipboard.setText(history_data['query'])
            self.status_message_label.setText("Query copied to clipboard.")

    def copy_history_to_editor(self, target_tab):
        history_data = self._get_selected_history_item(target_tab)
        if history_data:
            editor_stack = target_tab.findChild(QStackedWidget, "editor_stack")
            query_editor = target_tab.findChild(QTextEdit, "query_editor")
            query_editor.setPlainText(history_data['query'])
            
            # Switch back to the query editor view
            editor_stack.setCurrentIndex(0)
            # Find the buttons by object name or text
            query_view_btn = target_tab.findChild(QPushButton, "Query")
            history_view_btn = target_tab.findChild(QPushButton, "Query History")
            if query_view_btn: query_view_btn.setChecked(True)
            if history_view_btn: history_view_btn.setChecked(False)
            
            self.status_message_label.setText("Query copied to editor.")

    def remove_selected_history(self, target_tab):
        history_data = self._get_selected_history_item(target_tab)
        if not history_data: return
        
        history_id = history_data['id']
        if show_question_dialog(self, "Remove History", "Are you sure you want to remove the selected query history?"):
            try:
                self.db_manager.remove_history_item(history_id)
                self.load_connection_history(target_tab) # Refresh the view
                target_tab.findChild(QTextEdit, "history_details_view").clear()
                self.status_message_label.setText("Selected history item removed.")
            except Exception as e:
                show_critical_dialog(self, "Error", f"Failed to remove history item:\n{e}")

    def remove_all_history_for_connection(self, target_tab):
        db_combo_box = target_tab.findChild(QComboBox, "db_combo_box")
        conn_data = db_combo_box.currentData()
        if not conn_data:
            show_warning_dialog(self, "No Connection", "Please select a connection first.")
            return
        conn_id = conn_data.get("id")
        conn_name = db_combo_box.currentText()
        if show_question_dialog(self, "Remove All History", f"Are you sure you want to remove all history for the connection:\n'{conn_name}'?"):
            try:
                self.db_manager.remove_all_history_for_connection(conn_id)
                self.load_connection_history(target_tab)
                target_tab.findChild(QTextEdit, "history_details_view").clear()
                self.status_message_label.setText(f"All history for '{conn_name}' removed.")
            except Exception as e:
                show_critical_dialog(self, "Error", f"Failed to clear history for this connection:\n{e}")

    def show_schema_context_menu(self, position):
        index = self.schema_tree.indexAt(position)
        if not index.isValid():
            return

        item = self.schema_model.itemFromIndex(index)
        item_data = item.data(Qt.ItemDataRole.UserRole)

        # Check if it's a table/view item based on depth and data
        is_table_or_view = False
        if item_data:
            if item_data.get('db_type') == 'sqlite' and self.get_item_depth(item) == 1: # SQLite tables are top-level
                is_table_or_view = True
            elif item_data.get('db_type') == 'postgres' and item.parent(): # Postgres tables are under schema
                is_table_or_view = True

        if not is_table_or_view:
            return

        table_name = item.text()
        menu = QMenu()

        view_menu = menu.addMenu("View/Edit Data")

        query_all_action = QAction("Query all rows from Table", self)
        query_all_action.triggered.connect(
            lambda: self.query_table_rows(item_data, table_name, limit=None, execute_now=True))
        view_menu.addAction(query_all_action)

        preview_100_action = QAction("Preview first 100 rows", self)
        preview_100_action.triggered.connect(
            lambda: self.query_table_rows(item_data, table_name, limit=100, execute_now=True))
        view_menu.addAction(preview_100_action)

        last_100_action = QAction("Show last 100 rows", self)
        last_100_action.triggered.connect(
            lambda: self.query_table_rows(item_data, table_name, limit=100, order='desc', execute_now=True))
        view_menu.addAction(last_100_action)

        query_tool_action = QAction("Query Tool", self)
        query_tool_action.triggered.connect(
            lambda: self.open_query_tool_for_table(item_data, table_name))
        menu.addAction(query_tool_action)

        menu.exec(self.schema_tree.viewport().mapToGlobal(position))

    def open_query_tool_for_table(self, item_data, table_name):
        self.query_table_rows(item_data, table_name, execute_now=False)

    def query_table_rows(self, item_data, table_name, limit=None, execute_now=True, order=None):
        if not item_data: return
        conn_data = item_data.get('conn_data')
        new_tab = self.add_tab()
        query_editor = new_tab.findChild(QTextEdit, "query_editor")
        db_combo_box = new_tab.findChild(QComboBox, "db_combo_box")
        
        # Set the correct connection in the new tab's combobox
        for i in range(db_combo_box.count()):
            data = db_combo_box.itemData(i)
            if data and data.get('id') == conn_data.get('id'):
                db_combo_box.setCurrentIndex(i)
                break

        query = ""
        if item_data.get('db_type') == 'postgres':
            query = f'SELECT * FROM "{item_data.get("schema_name")}"."{table_name}"'
        elif item_data.get('db_type') == 'sqlite':
            query = f'SELECT * FROM "{table_name}"'

        if order:
             # This part for order is simplified; assumes a primary key exists for reliable ordering
             query += f" ORDER BY 1 {order.upper()}"

        if limit:
            query += f" LIMIT {limit}"
        
        query_editor.setPlainText(query)
        if execute_now:
            self.tab_widget.setCurrentWidget(new_tab) # Must set current tab to the new tab before executing
            self.execute_query()

    def undo_text(self):
        editor = self.get_current_editor()
        if editor: editor.undo()

    def redo_text(self):
        editor = self.get_current_editor()
        if editor: editor.redo()

    def cut_text(self):
        editor = self.get_current_editor()
        if editor: editor.cut()

    def copy_text(self):
        editor = self.get_current_editor()
        if editor: editor.copy()

    def paste_text(self):
        editor = self.get_current_editor()
        if editor: editor.paste()

    def closeEvent(self, event):
        """Ensures all threads are stopped before closing."""
        self.thread_pool.waitForDone()
        event.accept()
        
    def not_implemented(self):
        show_info_dialog(self, "Not Implemented", "This feature has not been implemented yet.")

    def show_preferences(self):
        self.not_implemented()

    def reset_layout(self):
        self.not_implemented()

    def view_logs(self):
        self.not_implemented()

    def configure_runtime(self):
        self.not_implemented()
    
    def find_text(self):
        editor = self.get_current_editor()
        if editor:
            show_info_dialog(self, "Find", "Find functionality is not implemented yet. Use Ctrl+F in the editor.")

    def toggle_fullscreen(self):
        """Toggles the main window's fullscreen state."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
            
    def show_about_dialog(self):
        """Shows the 'About' dialog box."""
        QMessageBox.about(self, "About SQL Client",
                          "A simple SQL client application.\n"
                          "Built with Python and PyQt6.")