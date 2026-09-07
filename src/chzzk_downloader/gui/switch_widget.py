"""모던 슬라이딩 토글 스위치 위젯 모듈 (T0109)."""

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget


class SwitchWidget(QWidget):
    """클릭으로 회색(OFF)과 파란색(ON) 색 전환 및 원이 좌우 이동하는 모던 토글 스위치 위젯."""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked: bool = checked
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:  # noqa: N802
        """스위치 활성화 여부를 반환합니다."""
        return self._checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        """스위치 상태를 변경하고 UI를 갱신합니다."""
        if self._checked != checked:
            self._checked = checked
            self.update()
            self.toggled.emit(self._checked)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event and event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, 22)

    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        radius = height / 2.0

        # 배경 둥근 사각형 그리기
        bg_color = QColor("#3b82f6") if self._checked else QColor("#4b5563")
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)

        # 원형 노브(Thumb) 그리기
        thumb_diameter = height - 4.0
        thumb_radius = thumb_diameter / 2.0
        if self._checked:
            thumb_x = width - height + 2.0
        else:
            thumb_x = 2.0
        thumb_y = 2.0

        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(
            QPointF(thumb_x + thumb_radius, thumb_y + thumb_radius),
            thumb_radius,
            thumb_radius,
        )
        painter.end()
