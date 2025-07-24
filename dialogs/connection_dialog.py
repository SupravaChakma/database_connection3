from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox, QWidget

class ConnectionDialog(QDialog):
    def __init__(self, parent=None, fields=None, conn_data=None, is_editing=False):
        super().__init__(parent)
        self.fields = fields if fields else []
        self.conn_data = conn_data if conn_data else {}
        
        self.setWindowTitle("Edit Connection" if is_editing else "New Connection")

        main_layout = QVBoxLayout(self)
        form_widget = QWidget()
        layout = QFormLayout(form_widget)
        
        self.inputs = {}
        for field_key, field_label in self.fields:
            self.inputs[field_key] = QLineEdit()
            # Populate with existing data if editing
            if is_editing and field_key in self.conn_data:
                self.inputs[field_key].setText(str(self.conn_data[field_key]))
            layout.addRow(field_label, self.inputs[field_key])
            
        main_layout.addWidget(form_widget)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        main_layout.addWidget(button_box)
        self.setLayout(main_layout)

    def get_data(self):
        data = {key: widget.text() for key, widget in self.inputs.items()}
        return data