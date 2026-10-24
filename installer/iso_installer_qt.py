#!/usr/bin/env python3
"""Qt6 graphical installer for the Diablo III Linux port.

This frontend drives port/install_game.py, which owns the complete pipeline:
ISO extraction, pinned ReXGlue SDK bootstrap/build, codegen, game build,
configuration, and optional launch.

Qt uses the native Wayland platform when available and a dark Fusion palette.
The Tkinter frontend remains as a fallback for hosts without PySide6.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

try:
    from PySide6.QtCore import QThread, QUrl, Signal, Qt
    from PySide6.QtGui import QColor, QDesktopServices, QPalette
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - host-dependent
    raise SystemExit(
        "PySide6/Qt6 is required for the Qt installer. Install python3-pyside6 "
        "(or use the Nix dev shell), or run the Tkinter installer."
    ) from exc

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "port" / "install_game.py"
DEFAULT_OUT = ROOT / "game"
DEFAULT_SDK_BUNDLE = ROOT / "sdk" / "rexglue-sdk-linux-amd64.tar.gz"


def is_nixos() -> bool:
    return Path("/etc/NIXOS").exists()


def apply_dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(38, 38, 40))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Base, QColor(28, 28, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(28, 28, 30))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Text, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Button, QColor(52, 52, 55))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 90, 90))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(64, 132, 196))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(130, 130, 130))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(130, 130, 130))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QPushButton { padding: 6px 12px; border-radius: 4px; }
        QPushButton:hover { background: #45454a; }
        QPushButton:default { background: #2d6a9f; }
        QLineEdit, QComboBox, QPlainTextEdit { padding: 4px; border-radius: 3px; }
        """
    )


class InstallWorker(QThread):
    line = Signal(str)
    finished = Signal(int)

    def __init__(self, command: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._command = command
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._cancelled = False

    def run(self) -> None:
        try:
            proc = subprocess.Popen(
                self._command,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            self.line.emit(f"ERROR: could not start installer: {exc}")
            self.finished.emit(1)
            return
        with self._lock:
            self._proc = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            self.line.emit(line.rstrip("\n"))
        self.finished.emit(proc.wait())

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
            self._cancelled = True
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                proc.terminate()
            except OSError:
                pass


class InstallerWindow(QMainWindow):
    def __init__(
        self,
        iso: Path | None,
        out: Path | None,
        sdk_bundle: Path | None,
        force: bool,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Souls of the Reaper — Linux Installer")
        self.resize(980, 760)
        self.setMinimumSize(820, 620)
        self._worker: InstallWorker | None = None
        self._phase_index = 0
        self._phase_total = 7
        self._last_error = ""
        self._out_dir = (out or DEFAULT_OUT).expanduser()

        if sdk_bundle is None and DEFAULT_SDK_BUNDLE.is_file() and not is_nixos():
            sdk_bundle = DEFAULT_SDK_BUNDLE

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("Install Diablo III for Linux")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QLabel(
            "Choose the Xbox 360 ISO/XISO and a destination folder. The installer "
            "extracts the disc, builds the pinned ReXGlue SDK, runs codegen, builds "
            "the Linux game, writes the configuration, and optionally launches it. "
            "The first build can take roughly 20–30 minutes."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        paths = QFormLayout()
        paths.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.iso_edit = QLineEdit(str(iso or ""))
        self.out_edit = QLineEdit(str(self._out_dir))
        paths.addRow("Disc image:", self._path_row(self.iso_edit, self._browse_iso))
        paths.addRow("Game data folder:", self._path_row(self.out_edit, self._browse_out))
        layout.addLayout(paths)

        options = QGroupBox("Install options")
        grid = QGridLayout(options)
        self.force_check = QCheckBox("Re-extract existing files")
        self.force_check.setChecked(force)
        self.fullscreen_check = QCheckBox("Fullscreen")
        self.fullscreen_check.setChecked(True)
        self.launch_check = QCheckBox("Launch when finished")
        self.launch_check.setChecked(True)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["720p", "1080p", "1440p", "4k"])
        self.resolution_combo.setCurrentText("1440p")
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["1", "2", "3"])
        self.scale_combo.setCurrentText("1")
        self.sdk_bundle_edit = QLineEdit(str(sdk_bundle or ""))
        self.sdk_bundle_edit.setPlaceholderText(
            "Optional prebuilt SDK bundle; auto-detected from sdk/ when available"
        )
        grid.addWidget(self.force_check, 0, 0, 1, 2)
        grid.addWidget(QLabel("Resolution:"), 0, 2)
        grid.addWidget(self.resolution_combo, 0, 3)
        grid.addWidget(self.fullscreen_check, 0, 4)
        grid.addWidget(QLabel("Internal scale:"), 1, 0)
        grid.addWidget(self.scale_combo, 1, 1)
        grid.addWidget(
            QLabel("1 = 720p/60 FPS · 2 = 1440p/higher detail · 3 = 2160p"),
            1,
            2,
            1,
            3,
        )
        grid.addWidget(self.launch_check, 2, 0, 1, 2)
        grid.addWidget(QLabel("SDK bundle:"), 3, 0)
        grid.addWidget(self.sdk_bundle_edit, 3, 1, 1, 3)
        sdk_browse = QPushButton("Browse…")
        sdk_browse.clicked.connect(self._browse_sdk_bundle)
        grid.addWidget(sdk_browse, 3, 4)
        grid.setColumnStretch(3, 1)
        layout.addWidget(options)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Select the Xbox 360 disc image to begin.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        log_box = QGroupBox("Installer log")
        log_layout = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setStyleSheet("font-family: monospace;")
        log_layout.addWidget(self.log)
        layout.addWidget(log_box, 1)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open game folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_out)
        self.copy_button = QPushButton("Copy launch command")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy_launch)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.install_button = QPushButton("Install & build")
        self.install_button.setDefault(True)
        self.install_button.clicked.connect(self._start)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    @staticmethod
    def _path_row(edit: QLineEdit, browse) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QPushButton("Browse…")
        button.clicked.connect(browse)
        row.addWidget(button)
        return widget

    def _browse_iso(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select the Diablo III Xbox 360 disc image",
            str(Path(self.iso_edit.text()).expanduser().parent)
            if self.iso_edit.text()
            else str(ROOT),
            "ISO images (*.iso *.xiso);;All files (*)",
        )
        if path:
            self.iso_edit.setText(path)

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select the game data folder",
            str(Path(self.out_edit.text()).expanduser())
            if self.out_edit.text()
            else str(ROOT),
        )
        if path:
            self.out_edit.setText(path)

    def _browse_sdk_bundle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a prebuilt ReXGlue SDK bundle",
            str(ROOT),
            "SDK bundle (*.tar.gz *.tgz);;All files (*)",
        )
        if path:
            self.sdk_bundle_edit.setText(path)

    def _resolved(self) -> tuple[Path, Path] | None:
        iso_text = self.iso_edit.text().strip()
        if not iso_text:
            QMessageBox.critical(self, "Missing disc image", "Choose or enter the ISO/XISO path.")
            return None
        iso = Path(iso_text).expanduser()
        if not iso.is_absolute():
            iso = ROOT / iso
        if not iso.is_file():
            QMessageBox.critical(self, "Disc image not found", f"The file does not exist:\n\n{iso}")
            return None
        out = Path(self.out_edit.text().strip() or DEFAULT_OUT).expanduser()
        if not out.is_absolute():
            out = ROOT / out
        if out.exists() and not out.is_dir():
            QMessageBox.critical(self, "Invalid destination", f"Not a folder:\n\n{out}")
            return None
        if not INSTALLER.is_file():
            QMessageBox.critical(self, "Installer missing", f"Could not find:\n\n{INSTALLER}")
            return None
        return iso.resolve(), out.resolve()

    def _start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        paths = self._resolved()
        if paths is None:
            return
        iso, out = paths
        self._out_dir = out
        self._phase_index = 0
        self._phase_total = 7
        self._last_error = ""
        self.log.clear()
        self.progress.setValue(0)
        self.status.setText("Preparing installation…")
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self._append(f"Disc image: {iso}")
        self._append(f"Game data:  {out}")
        self._append(
            f"Resolution: {self.resolution_combo.currentText()}  "
            f"internal scale: {self.scale_combo.currentText()}x  "
            f"fullscreen: {'yes' if self.fullscreen_check.isChecked() else 'no'}"
        )
        if self.force_check.isChecked():
            self._append("Re-extract existing files: yes")
        self._append("")

        command = [
            sys.executable,
            "-u",
            str(INSTALLER),
            "--iso",
            str(iso),
            "--out",
            str(out),
            "--resolution",
            self.resolution_combo.currentText(),
            "--res-scale",
            self.scale_combo.currentText(),
            "--fullscreen",
            "true" if self.fullscreen_check.isChecked() else "false",
            "--borderless",
            "false",
        ]
        if self.force_check.isChecked():
            command.append("--force")
        sdk_bundle = self.sdk_bundle_edit.text().strip()
        if sdk_bundle:
            command.extend(["--sdk-bundle", sdk_bundle])
        if self.launch_check.isChecked():
            command.append("--launch")

        self._worker = InstallWorker(command, self)
        self._worker.line.connect(self._handle_line)
        self._worker.finished.connect(self._handle_finished)
        self._set_running(True)
        self._worker.start()

    def _set_running(self, running: bool) -> None:
        for widget in (
            self.iso_edit,
            self.out_edit,
            self.sdk_bundle_edit,
            self.force_check,
            self.fullscreen_check,
            self.launch_check,
            self.resolution_combo,
            self.scale_combo,
            self.install_button,
        ):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.close_button.setEnabled(not running)

    def _handle_line(self, line: str) -> None:
        if line:
            self._append(line)
        phase = re.match(r"==>\s*\[(\d+)/(\d+)\]\s*(.*)", line)
        if phase:
            self._phase_index = int(phase.group(1))
            self._phase_total = max(1, int(phase.group(2)))
            self.progress.setValue(int(100.0 * (self._phase_index - 1) / self._phase_total))
            self.status.setText(f"[{self._phase_index}/{self._phase_total}] {phase.group(3).strip()}")
            return
        extracting = re.match(r"\[(\d+)/(\d+)\]\s*(.*)", line)
        if extracting and self._phase_index == 1:
            index = int(extracting.group(1))
            total = max(1, int(extracting.group(2)))
            self.progress.setValue(
                int(100.0 * ((self._phase_index - 1) + index / total) / self._phase_total)
            )
            self.status.setText(f"Extracting {index}/{total}: {extracting.group(3).strip()}")
            return
        if line.startswith("Detected language:"):
            self.status.setText(line)
        elif line.startswith("ERROR:") or "error:" in line.lower():
            self._last_error = line
            self.status.setText("Installation failed.")

    def _handle_finished(self, rc: int) -> None:
        self._worker = None
        self._set_running(False)
        if rc == 0:
            self.progress.setValue(100)
            self.status.setText("Installation complete.")
            self.open_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            launched = self.launch_check.isChecked()
            QMessageBox.information(
                self,
                "Installation complete",
                "Diablo III is installed and built successfully.\n\n"
                f"Game data: {self._out_dir}\n"
                "Launch: ./launch-diablo3.sh\n\n"
                + ("The game has been launched." if launched else "Use the launch command above."),
            )
        else:
            self.status.setText("Installation failed.")
            detail = self._last_error or "The installer exited with an error. See the log above."
            self._append(detail)
            QMessageBox.critical(self, "Installation failed", detail)

    def _cancel(self) -> None:
        if self._worker is None:
            return
        self.cancel_button.setEnabled(False)
        self.status.setText("Cancelling…")
        self._append("Cancelling installation…")
        self._worker.cancel()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._worker is not None and self._worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Cancel installation?",
                "The installation is still running. Cancel it and close the installer?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(3000)
        event.accept()

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _open_out(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._out_dir)))

    def _copy_launch(self) -> None:
        QApplication.clipboard().setText(f'cd "{ROOT}"\n./launch-diablo3.sh')
        self.status.setText("Launch command copied to the clipboard.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, help="pre-fill the ISO/XISO path")
    parser.add_argument("--out", type=Path, help=f"game data folder (default: {DEFAULT_OUT})")
    parser.add_argument("--sdk-bundle", type=Path, help="pre-fill a prebuilt SDK bundle")
    parser.add_argument("--force", action="store_true", help="re-extract existing files")
    parser.add_argument("--version", action="version", version="Souls of the Reaper Qt installer 2.0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "xcb"
    os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Souls of the Reaper Installer")
    apply_dark_palette(app)
    window = InstallerWindow(args.iso, args.out, args.sdk_bundle, args.force)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
