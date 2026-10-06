"""VOD 구간 설정을 위한 시/분/초 타임스탬프 입력 위젯 모듈 (T0601)."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QHideEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)

from chzzk_downloader.core.section_parser import parse_timestamp


class _FastRepeatSpinBoxMixin:
    """마우스 화살표 롱프레스 시 초기 250ms 후 50ms 주기로 빠른 반복 증감을 지원하는 믹스인."""

    _repeat_timer: QTimer
    _repeat_step: int

    def _setup_repeat(self) -> None:
        self._repeat_timer = QTimer(self)  # type: ignore[arg-type]
        self._repeat_step = 0
        self._repeat_timer.timeout.connect(self._on_repeat_timeout)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)  # type: ignore[attr-defined]
        sc = self.style().hitTestComplexControl(  # type: ignore[attr-defined]
            QStyle.ComplexControl.CC_SpinBox,
            opt,
            event.pos(),
            self,  # type: ignore[arg-type]
        )
        if sc == QStyle.SubControl.SC_SpinBoxUp:
            self._repeat_step = 1
            self.stepBy(1)  # type: ignore[attr-defined]
            self._repeat_timer.start(250)
            return
        if sc == QStyle.SubControl.SC_SpinBoxDown:
            self._repeat_step = -1
            self.stepBy(-1)  # type: ignore[attr-defined]
            self._repeat_timer.start(250)
            return
        super().mousePressEvent(event)  # type: ignore[misc]

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._repeat_timer.isActive():
            self._repeat_timer.stop()
            self._repeat_step = 0
        super().mouseReleaseEvent(event)  # type: ignore[misc]

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        if self._repeat_timer.isActive():
            self._repeat_timer.stop()
            self._repeat_step = 0
        super().hideEvent(event)  # type: ignore[misc]

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        if self._repeat_timer.isActive():
            self._repeat_timer.stop()
            self._repeat_step = 0
        super().focusOutEvent(event)  # type: ignore[misc]

    def is_repeating(self) -> bool:
        """반복 타이머 동작 여부를 반환합니다."""
        return self._repeat_timer.isActive()

    def start_repeat_for_test(self, step: int = 1, interval_ms: int = 50) -> None:
        """테스트 검증용 반복 타이머를 구동합니다."""
        self._repeat_step = step
        self._repeat_timer.start(interval_ms)

    def _on_repeat_timeout(self) -> None:
        if self._repeat_timer.interval() == 250:
            self._repeat_timer.setInterval(50)
        self.stepBy(self._repeat_step)  # type: ignore[attr-defined]


class _ZeroPaddedSpinBox(_FastRepeatSpinBoxMixin, QSpinBox):
    """2자리 0 채움(00, 01, ...)으로 렌더링하는 정수 스핀박스."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_repeat()

    def textFromValue(self, val: int) -> str:  # noqa: N802
        return f"{val:02d}"


class _ZeroPaddedDoubleSpinBox(_FastRepeatSpinBoxMixin, QDoubleSpinBox):
    """2자리 정수 및 2자리 소수점(00.00)으로 렌더링하는 실수 스핀박스."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_repeat()

    def textFromValue(self, val: float) -> str:  # noqa: N802
        return f"{val:05.2f}"


class SectionTimeWidget(QWidget):
    """샤나인코더 스타일 시/분/초 분할 스핀박스 위젯 (상하 증감 화살표, 키보드 방향키, 마우스 롱클릭 지원)."""

    textChanged = pyqtSignal(str)  # noqa: N815

    def __init__(
        self, default_text: str = "00:00:00.00", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._max_seconds: float | None = None
        self._min_seconds: float = 0.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.hour_spin = _ZeroPaddedSpinBox(self)
        self.hour_spin.setRange(0, 999)
        self.hour_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hour_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.hour_spin.setFixedWidth(58)

        self.colon1 = QLabel(":", self)
        self.colon1.setStyleSheet("color: #9ca3af; font-weight: bold; border: none;")

        self.min_spin = _ZeroPaddedSpinBox(self)
        self.min_spin.setRange(0, 59)
        self.min_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.min_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.min_spin.setFixedWidth(58)

        self.colon2 = QLabel(":", self)
        self.colon2.setStyleSheet("color: #9ca3af; font-weight: bold; border: none;")

        self.sec_spin = _ZeroPaddedDoubleSpinBox(self)
        self.sec_spin.setRange(0.0, 59.99)
        self.sec_spin.setDecimals(2)
        self.sec_spin.setSingleStep(1.0)
        self.sec_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sec_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.sec_spin.setFixedWidth(78)

        self.hour_spin.stepBy = self._make_stepper(3600.0)
        self.min_spin.stepBy = self._make_stepper(60.0)
        self.sec_spin.stepBy = self._make_stepper(1.0)

        layout.addWidget(self.hour_spin)
        layout.addWidget(self.colon1)
        layout.addWidget(self.min_spin)
        layout.addWidget(self.colon2)
        layout.addWidget(self.sec_spin)

        self.hour_spin.valueChanged.connect(self._on_value_changed)
        self.min_spin.valueChanged.connect(self._on_value_changed)
        self.sec_spin.valueChanged.connect(self._on_value_changed)

        self._raw_invalid_text: str | None = None
        if default_text:
            self.setText(default_text)

    def _make_stepper(self, multiplier: float) -> Any:
        def custom_step_by(steps: int) -> None:
            cur = self.total_seconds()
            target = cur + steps * multiplier
            if target < self._min_seconds:
                target = self._min_seconds
            if self._max_seconds is not None and target > self._max_seconds:
                target = self._max_seconds
            self.set_seconds(target)

        return custom_step_by

    def set_max_seconds(self, max_sec: float | None) -> None:
        self._max_seconds = max_sec
        if max_sec is not None and self.total_seconds() > max_sec:
            self.set_seconds(max_sec)

    def set_min_seconds(self, min_sec: float) -> None:
        self._min_seconds = max(0.0, float(min_sec))
        if self.total_seconds() < self._min_seconds:
            self.set_seconds(self._min_seconds)

    def _on_value_changed(self) -> None:
        self._raw_invalid_text = None
        self.textChanged.emit(self.text())

    def total_seconds(self) -> float:
        return (
            self.hour_spin.value() * 3600.0
            + self.min_spin.value() * 60.0
            + self.sec_spin.value()
        )

    def is_valid_time(self) -> bool:
        return self._raw_invalid_text is None

    def set_seconds(self, seconds: float) -> None:
        self._raw_invalid_text = None
        sec_val = max(self._min_seconds, float(seconds))
        if self._max_seconds is not None:
            sec_val = min(self._max_seconds, sec_val)
        h = int(sec_val // 3600)
        m = int((sec_val % 3600) // 60)
        s = round(sec_val % 60, 2)
        self.hour_spin.blockSignals(True)
        self.min_spin.blockSignals(True)
        self.sec_spin.blockSignals(True)
        self.hour_spin.setValue(h)
        self.min_spin.setValue(m)
        self.sec_spin.setValue(s)
        self.hour_spin.blockSignals(False)
        self.min_spin.blockSignals(False)
        self.sec_spin.blockSignals(False)
        self.textChanged.emit(self.text())

    def text(self) -> str:
        if self._raw_invalid_text is not None:
            return self._raw_invalid_text
        h = self.hour_spin.value()
        m = self.min_spin.value()
        s = self.sec_spin.value()
        if s == int(s):
            return f"{h:02d}:{m:02d}:{int(s):02d}"
        return f"{h:02d}:{m:02d}:{s:05.2f}"

    def setText(self, text_val: str) -> None:  # noqa: N802
        try:
            sec = parse_timestamp(text_val)
            self._raw_invalid_text = None
            self.set_seconds(sec)
        except (ValueError, TypeError):
            self._raw_invalid_text = text_val
            self.textChanged.emit(self.text())

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.hour_spin.setEnabled(enabled)
        self.min_spin.setEnabled(enabled)
        self.sec_spin.setEnabled(enabled)

    def setStyleSheet(self, style: str) -> None:  # noqa: N802
        super().setStyleSheet(style)
        self.hour_spin.setStyleSheet(style)
        self.min_spin.setStyleSheet(style)
        self.sec_spin.setStyleSheet(style)
