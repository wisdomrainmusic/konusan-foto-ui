# konusan-ui/ui_app.py
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QFileDialog,
    QVBoxLayout, QHBoxLayout, QTextEdit, QMessageBox, QLineEdit, QCheckBox
)

from run_pipeline import run_job


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output_ui"


def open_folder(path: Path):
    try:
        os.startfile(str(path))
    except Exception:
        pass


class Worker(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, img: str, aud: str, body_motion: bool):
        super().__init__()
        self.img = img
        self.aud = aud
        self.body_motion = body_motion

    def run(self):
        try:
            def cb(msg: str):
                self.log.emit(msg)
            out = run_job(self.img, self.aud, log_cb=cb, body_motion_enabled=self.body_motion)
            self.done.emit(str(out))
        except Exception as e:
            self.fail.emit(str(e))


class KonusanUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Konuşan Foto – Clean UI (SadTalker)")
        self.setFixedSize(560, 680)

        self.image_path = ""
        self.audio_path = ""
        self.worker = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Preview
        self.preview = QLabel("Foto preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(260)
        self.preview.setStyleSheet("border: 1px solid #444; border-radius: 8px;")
        layout.addWidget(self.preview)

        # File rows
        row1 = QHBoxLayout()
        self.img_line = QLineEdit()
        self.img_line.setPlaceholderText("Foto yolu (jpg/png/webp)")
        btn_img = QPushButton("📷 Foto Seç")
        btn_img.clicked.connect(self.select_image)
        row1.addWidget(self.img_line)
        row1.addWidget(btn_img)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.aud_line = QLineEdit()
        self.aud_line.setPlaceholderText("Ses yolu (wav/mp3/m4a)")
        btn_aud = QPushButton("🎤 Ses Seç")
        btn_aud.clicked.connect(self.select_audio)
        row2.addWidget(self.aud_line)
        row2.addWidget(btn_aud)
        layout.addLayout(row2)

        self.body_motion_checkbox = QCheckBox("✨ Body Motion (experimental)")
        layout.addWidget(self.body_motion_checkbox)

        # Render buttons
        row3 = QHBoxLayout()
        self.btn_render = QPushButton("🚀 Render")
        self.btn_render.clicked.connect(self.on_render)
        self.btn_open = QPushButton("📂 Output Aç")
        self.btn_open.clicked.connect(lambda: open_folder(OUT_DIR))
        row3.addWidget(self.btn_render)
        row3.addWidget(self.btn_open)
        layout.addLayout(row3)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas; font-size: 11px;")
        layout.addWidget(self.log)

        self.setLayout(layout)

    def select_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Foto seç", str(ROOT),
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if not path:
            return
        self.image_path = path
        self.img_line.setText(path)

        # preview
        pix = QPixmap(path)
        if not pix.isNull():
            pix = pix.scaled(
                self.preview.width(), self.preview.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview.setPixmap(pix)

    def select_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ses seç", str(ROOT),
            "Audio (*.wav *.mp3 *.m4a)"
        )
        if not path:
            return
        self.audio_path = path
        self.aud_line.setText(path)

    def on_render(self):
        img = self.img_line.text().strip()
        aud = self.aud_line.text().strip()

        if not img or not Path(img).exists():
            QMessageBox.warning(self, "Eksik", "Foto seçmedin veya yol hatalı.")
            return
        if not aud or not Path(aud).exists():
            QMessageBox.warning(self, "Eksik", "Ses seçmedin veya yol hatalı.")
            return

        self.btn_render.setEnabled(False)
        self.log.append("[UI] Render başladı...")

        body_motion = self.body_motion_checkbox.isChecked()
        self.worker = Worker(img, aud, body_motion)
        self.worker.log.connect(self.log.append)
        self.worker.done.connect(self.on_done)
        self.worker.fail.connect(self.on_fail)
        self.worker.start()

    def on_done(self, out_path: str):
        self.log.append(f"\n[UI] ✅ Bitti: {out_path}")
        self.btn_render.setEnabled(True)
        open_folder(OUT_DIR)

    def on_fail(self, err: str):
        self.log.append(f"\n[UI] ❌ Hata: {err}")
        self.btn_render.setEnabled(True)
        QMessageBox.critical(self, "Hata", err)


def main():
    app = QApplication(sys.argv)
    w = KonusanUI()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
