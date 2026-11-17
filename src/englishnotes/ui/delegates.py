from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from englishnotes.ui.icons import icon


class EntryDelegate(QStyledItemDelegate):
    """Two-tone lesson rows and compact note rows; underlying item data is unchanged."""

    def __init__(self, kind, parent):
        super().__init__(parent)
        self.kind = kind

    def sizeHint(self, option, index):
        return QSize(0, 70 if self.kind == "lesson" else 48)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        rect = QRectF(option.rect).adjusted(1, 2, -1, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or hovered:
            painter.setBrush(QColor("#28334e" if selected else "#1f2733"))
            painter.drawRoundedRect(rect, 9, 9)
        if selected:
            painter.setBrush(QColor("#a3afff"))
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top() + 13, 3, rect.height() - 26), 1.5, 1.5
            )
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#697dae"), 1))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        color = "#b8c3ff" if selected else "#929eb2"
        bounds = option.rect
        icon("book" if self.kind == "lesson" else "note", color).paint(
            painter, bounds.left() + 12, bounds.top() + 15, 18, 18
        )
        x = bounds.left() + 41
        width = max(0, bounds.width() - 53)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").splitlines()
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#eef1ff" if selected else "#ccd5e3"))
        title = painter.fontMetrics().elidedText(
            text[0] if text else "", Qt.TextElideMode.ElideRight, width
        )
        painter.drawText(x, bounds.top() + 29, title)
        if self.kind == "lesson" and len(text) > 1:
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor("#a5b1ca" if selected else "#929eb2"))
            painter.drawText(x, bounds.top() + 49, text[-1])
        painter.restore()
