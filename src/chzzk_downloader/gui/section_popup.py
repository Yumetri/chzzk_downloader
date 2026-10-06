"""VOD 구간 다운로드를 위한 구간 설정 Non-modal 팝업 위젯 (T0601)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.core.section_parser import (
    format_timestamp,
    parse_timestamp,
    validate_section,
)


class _ZeroPaddedSpinBox(QSpinBox):
    """2자리 0 채움(00, 01, ...)으로 렌더링하는 정수 스핀박스."""

    def textFromValue(self, val: int) -> str:  # noqa: N802
        return f"{val:02d}"


class _ZeroPaddedDoubleSpinBox(QDoubleSpinBox):
    """2자리 정수 및 2자리 소수점(00.00)으로 렌더링하는 실수 스핀박스."""

    def textFromValue(self, val: float) -> str:  # noqa: N802
        return f"{val:05.2f}"


class SectionTimeWidget(QWidget):
    """샤나인코더 스타일 시/분/초 분할 스핀박스 위젯 (상하 증감 화살표, 키보드 방향키, 마우스 롱클릭 지원)."""

    textChanged = pyqtSignal(str)  # noqa: N815

    def __init__(
        self, default_text: str = "00:00:00.00", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.hour_spin = _ZeroPaddedSpinBox(self)
        self.hour_spin.setRange(0, 999)
        self.hour_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hour_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)

        self.colon1 = QLabel(":", self)
        self.colon1.setStyleSheet("color: #9ca3af; font-weight: bold; border: none;")

        self.min_spin = _ZeroPaddedSpinBox(self)
        self.min_spin.setRange(0, 59)
        self.min_spin.setWrapping(True)
        self.min_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.min_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)

        self.colon2 = QLabel(":", self)
        self.colon2.setStyleSheet("color: #9ca3af; font-weight: bold; border: none;")

        self.sec_spin = _ZeroPaddedDoubleSpinBox(self)
        self.sec_spin.setRange(0.0, 59.99)
        self.sec_spin.setDecimals(2)
        self.sec_spin.setSingleStep(1.0)
        self.sec_spin.setWrapping(True)
        self.sec_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sec_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)

        self.hour_spin.setFixedWidth(46)
        self.min_spin.setFixedWidth(46)
        self.sec_spin.setFixedWidth(64)

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
        sec_val = max(0.0, float(seconds))
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


class SectionPopup(QFrame):
    """메인 UI 동작성에 영향을 주지 않는 경량 구간 설정 팝오버 팝업."""

    section_changed = pyqtSignal(bool)  # (is_valid)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._duration: float = 0.0

        self.setStyleSheet(
            "QFrame { background-color: #1f2937; border: 1px solid #374151; "
            "border-radius: 6px; padding: 6px; }"
            "QLabel { color: #f3f4f6; font-size: 11px; border: none; }"
            "QCheckBox { color: #f3f4f6; font-size: 11px; spacing: 6px; border: none; }"
            "QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #4b5563; background: #111827; }"
            "QCheckBox::indicator:checked { background: #3b82f6; border: 1px solid #3b82f6; }"
            "QSpinBox, QDoubleSpinBox { background-color: #111827; color: #f3f4f6; border: 1px solid #4b5563; "
            "border-radius: 4px; padding: 2px 2px; font-size: 11px; font-family: monospace; }"
            "QSpinBox:disabled, QDoubleSpinBox:disabled { background-color: #1f2937; color: #6b7280; border: 1px solid #374151; }"
            "QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; "
            "width: 14px; border-left: 1px solid #374151; border-bottom: 1px solid #374151; background-color: #1f2937; }"
            "QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; "
            "width: 14px; border-left: 1px solid #374151; background-color: #1f2937; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 시작 시간 행
        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        self.start_check = QCheckBox("시작 시간", self)
        self.start_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_edit = SectionTimeWidget("00:00:00.00", self)
        self.start_edit.setEnabled(False)
        start_row.addWidget(self.start_check)
        start_row.addWidget(self.start_edit)
        layout.addLayout(start_row)

        # 종료 시간 행
        end_row = QHBoxLayout()
        end_row.setSpacing(8)
        self.end_check = QCheckBox("종료 시간", self)
        self.end_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_edit = SectionTimeWidget("00:00:00.00", self)
        self.end_edit.setEnabled(False)
        end_row.addWidget(self.end_check)
        end_row.addWidget(self.end_edit)
        layout.addLayout(end_row)

        # 경고 및 에러 피드백 라벨
        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #ef4444; font-size: 10px; border: none;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        # 시그널 연결
        self.start_check.toggled.connect(self._on_check_toggled)
        self.end_check.toggled.connect(self._on_check_toggled)
        self.start_edit.textChanged.connect(self._validate_inputs)
        self.end_edit.textChanged.connect(self._validate_inputs)

    def set_duration(self, duration: float) -> None:
        """영상 전체 길이를 등록하고 종료 시간 기본 텍스트를 갱신합니다."""
        self._duration = max(0.0, float(duration))
        dur_str = format_timestamp(self._duration, use_fraction=True)
        self.end_edit.setText(dur_str)

    def _on_check_toggled(self) -> None:
        """체크박스 토글 시 입력창 활성화 상태를 변경하고 유효성을 재검증합니다."""
        self.start_edit.setEnabled(self.start_check.isChecked())
        self.end_edit.setEnabled(self.end_check.isChecked())
        self._validate_inputs()

    def is_valid(self) -> bool:
        """현재 입력된 구간의 유효성을 반환합니다."""
        return self._validate_inputs()

    def _validate_inputs(self) -> bool:
        """현재 입력된 시간의 유효성을 실시간으로 검사하고 피드백을 반영합니다."""
        start_active = self.start_check.isChecked()
        end_active = self.end_check.isChecked()

        # 둘 다 비활성화인 경우 전체 다운로드이므로 항상 유효
        if not start_active and not end_active:
            self._set_error("")
            self.section_changed.emit(True)
            return True

        start_text = self.start_edit.text() if start_active else "00:00:00"
        end_text = self.end_edit.text() if end_active else None

        try:
            validate_section(
                start_text,
                end_text,
                duration=self._duration if self._duration > 0 else None,
            )
            self._set_error("")
            self.section_changed.emit(True)
            return True
        except ValueError as err:
            self._set_error(str(err))
            self.section_changed.emit(False)
            return False

    def _set_error(self, message: str) -> None:
        """에러 메시지를 표시하거나 숨깁니다."""
        if message:
            self.error_label.setText(message)
            self.error_label.show()
            if self.start_check.isChecked():
                self.start_edit.setStyleSheet(
                    "border: 1px solid #ef4444; color: #ef4444;"
                )
            if self.end_check.isChecked():
                self.end_edit.setStyleSheet(
                    "border: 1px solid #ef4444; color: #ef4444;"
                )
        else:
            self.error_label.setText("")
            self.error_label.hide()
            self.start_edit.setStyleSheet("")
            self.end_edit.setStyleSheet("")

    def get_section_range(self) -> tuple[float | None, float | None]:
        """선택된 구간 (시작_초, 종료_초)을 반환합니다. 지정되지 않거나 파싱 실패 시 None을 반환합니다."""
        start_active = self.start_check.isChecked()
        end_active = self.end_check.isChecked()

        if not start_active and not end_active:
            return None, None

        if start_active and not self.start_edit.is_valid_time():
            return None, None
        if end_active and not self.end_edit.is_valid_time():
            return None, None

        try:
            start_val = self.start_edit.total_seconds() if start_active else 0.0
            end_val = (
                self.end_edit.total_seconds()
                if end_active
                else (self._duration if self._duration > 0 else None)
            )
            return start_val, end_val
        except (ValueError, TypeError):
            return None, None

    def set_section_range(self, start: float | None, end: float | None) -> None:
        """외부에서 구간 (시작_초, 종료_초)을 프로그래밍 방식으로 설정합니다."""
        if start is not None:
            self.start_check.setChecked(True)
            self.start_edit.set_seconds(start)
        else:
            self.start_check.setChecked(False)

        if end is not None:
            self.end_check.setChecked(True)
            self.end_edit.set_seconds(end)
        else:
            self.end_check.setChecked(False)

        self._validate_inputs()

    def reset(self) -> None:
        """구간 설정을 기본 상태(미체크, 기본 시간)로 초기화합니다."""
        self.start_check.setChecked(False)
        self.end_check.setChecked(False)
        self.start_edit.setText("00:00:00")
        self.start_edit.setEnabled(False)
        self.end_edit.setText(
            format_timestamp(self._duration) if self._duration > 0 else "00:00:00"
        )
        self.end_edit.setEnabled(False)
        self._set_error("")
        self.section_changed.emit(True)

    def show_below(self, target_widget: QWidget) -> None:
        """대상 위젯의 바로 아래 위치에 팝업을 표시합니다."""
        target_pos = target_widget.mapToGlobal(QPoint(0, target_widget.height()))
        self.move(target_pos)
        self.show()
