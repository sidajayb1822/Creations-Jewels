from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent


class DropZone(QLabel):
    """Drag-and-drop target that accepts a single .xlsx file."""

    file_dropped = Signal(str)

    _IDLE_STYLE = """
        QLabel {
            border: 2px dashed #c7d2fe;
            border-radius: 12px;
            background: #eef2ff;
            color: #6366f1;
            font-size: 14px;
            font-weight: 600;
        }
    """
    _HOVER_STYLE = """
        QLabel {
            border: 2px dashed #6366f1;
            border-radius: 12px;
            background: #e0e7ff;
            color: #4338ca;
            font-size: 14px;
            font-weight: 600;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("Drop Emperor BOM Excel file here\n(.xlsx)")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(self._IDLE_STYLE)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(".xlsx")
                   for u in event.mimeData().urls()):
                event.acceptProposedAction()
                self.setStyleSheet(self._HOVER_STYLE)
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._IDLE_STYLE)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._IDLE_STYLE)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".xlsx"):
                self.file_dropped.emit(path)
                return
