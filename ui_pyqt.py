import os
from PyQt5.QtWidgets import (
    QMainWindow, QPushButton, QFileDialog, QLabel,
    QVBoxLayout, QWidget, QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt
import ocr_engine

# Ensure userdata directory exists
os.makedirs("userdata", exist_ok=True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shift Tracker MVP")
        self.setGeometry(200, 200, 600, 400)

        layout = QVBoxLayout()

        # Instruction label
        self.label = QLabel("Upload your schedule image (PNG/JPG/JPEG/BMP).")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        # Upload button
        self.upload_button = QPushButton("Upload Image")
        self.upload_button.clicked.connect(self.upload_image)
        layout.addWidget(self.upload_button)

        # OCR result display
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText("OCR result will appear here after upload...")
        layout.addWidget(self.result_view)

        # Minimal hint
        self.hint = QLabel("Note: PDF support not included in this minimal setup.")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

        # Container
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def upload_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp);;PDF (*.pdf)"
        )

        if not file_path:
            return

        # Basic handling for PDFs (we don't support conversion in this minimal setup)
        if file_path.lower().endswith(".pdf"):
            QMessageBox.information(
                self,
                "PDF selected",
                "PDF selected — PDF-to-image conversion is not implemented in this minimal setup.\n"
                "Please export the schedule as a PNG/JPG and try again."
            )
            return

        self.label.setText(f"Selected: {os.path.basename(file_path)}")
        self.result_view.setPlainText("Processing...")

        # Run OCR (synchronous; fast for MVP)
        ocr_text, info = ocr_engine.process_image(file_path)

        # Show results and basic info
        header = f"File: {os.path.basename(file_path)}\n{info}\n\n"
        self.result_view.setPlainText(header + ocr_text)

        # Inform user if OCR failed for some reason
        if ocr_text.startswith("[ERROR]"):
            QMessageBox.warning(self, "OCR error", ocr_text)

