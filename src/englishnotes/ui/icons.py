"""Small vector icons, drawn by Qt so frozen builds need no extra asset files."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


@lru_cache(maxsize=48)
def icon(name: str, color: str = "#a4afc1", size: int = 20) -> QIcon:
    image = QPixmap(size * 2, size * 2)
    image.setDevicePixelRatio(2)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    painter.setPen(
        QPen(
            QColor(color),
            1.6,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )

    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    if name == "plus":
        line(12, 5, 12, 19)
        line(5, 12, 19, 12)
    elif name in ("note", "book"):
        painter.drawRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
        if name == "book":
            line(9, 3, 9, 21)
            line(12, 8, 16, 8)
        else:
            line(9, 9, 15, 9)
            line(9, 13, 15, 13)
            line(9, 17, 13, 17)
    elif name == "join":
        line(4, 12, 15, 12)
        line(11, 8, 15, 12)
        line(11, 16, 15, 12)
        path = QPainterPath(QPointF(14, 4))
        path.lineTo(19, 4)
        path.quadTo(21, 4, 21, 6)
        path.lineTo(21, 18)
        path.quadTo(21, 20, 19, 20)
        path.lineTo(14, 20)
        painter.drawPath(path)
    elif name == "users":
        painter.drawEllipse(QRectF(6, 3, 7, 7))
        path = QPainterPath(QPointF(3, 20))
        path.lineTo(3, 17)
        path.cubicTo(3, 12, 16, 12, 16, 17)
        path.lineTo(16, 20)
        painter.drawPath(path)
        path = QPainterPath(QPointF(17, 4))
        path.cubicTo(22, 5, 22, 10, 18, 11)
        painter.drawPath(path)
        path = QPainterPath(QPointF(19, 14))
        path.quadTo(22, 15, 22, 20)
        painter.drawPath(path)
    elif name == "finish":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        line(8, 12, 11, 15)
        line(11, 15, 17, 9)
    elif name == "trash":
        line(4, 7, 20, 7)
        line(9, 4, 15, 4)
        line(9, 4, 8, 7)
        line(15, 4, 16, 7)
        path = QPainterPath(QPointF(6, 7))
        path.lineTo(7, 20)
        path.lineTo(17, 20)
        path.lineTo(18, 7)
        painter.drawPath(path)
        line(10, 11, 10, 16)
        line(14, 11, 14, 16)
    elif name == "conflict":
        painter.drawRoundedRect(QRectF(3, 3, 7, 18), 2, 2)
        painter.drawRoundedRect(QRectF(14, 3, 7, 18), 2, 2)
        line(6, 9, 7, 9)
        line(17, 15, 18, 15)
    painter.end()
    return QIcon(image)
