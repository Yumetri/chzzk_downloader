"""VOD 구간 다운로드를 위한 구간 설정 Non-modal 팝업 위젯 (T0601)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.core.section_parser import (
    format_timestamp,
    validate_section,
)
from chzzk_downloader.gui.section_time_widget import SectionTimeWidget

_ASSETS_DIR = Path(__file__).parent / "assets"
_UP_SVG = str((_ASSETS_DIR / "arrow_up.svg").resolve()).replace("\\", "/")
_DOWN_SVG = str((_ASSETS_DIR / "arrow_down.svg").resolve()).replace("\\", "/")


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
            f"QFrame {{ background-color: #1f2937; border: 1px solid #374151; "
            f"border-radius: 6px; padding: 6px; }}"
            f"QLabel {{ color: #f3f4f6; font-size: 11px; border: none; }}"
            f"QCheckBox {{ color: #f3f4f6; font-size: 11px; spacing: 6px; border: none; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px; border: 1px solid #4b5563; background: #111827; }}"
            f"QCheckBox::indicator:checked {{ background: #3b82f6; border: 1px solid #3b82f6; }}"
            f"QSpinBox, QDoubleSpinBox {{ background-color: #111827; color: #f3f4f6; border: 1px solid #4b5563; "
            f"border-radius: 4px; padding: 2px 14px 2px 2px; font-size: 11px; font-family: monospace; }}"
            f"QSpinBox:disabled, QDoubleSpinBox:disabled {{ background-color: #1f2937; color: #6b7280; border: 1px solid #374151; }}"
            f"QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; "
            f"width: 14px; border-left: 1px solid #374151; border-bottom: 1px solid #374151; background-color: #1f2937; }}"
            f"QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{ background-color: #374151; }}"
            f"QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; "
            f"width: 14px; border-left: 1px solid #374151; background-color: #1f2937; }}"
            f"QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background-color: #374151; }}"
            f"QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url('{_UP_SVG}'); width: 7px; height: 5px; }}"
            f"QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url('{_DOWN_SVG}'); width: 7px; height: 5px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        self.start_check = QCheckBox("시작 시간", self)
        self.start_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_edit = SectionTimeWidget("00:00:00.00", self)
        self.start_edit.setEnabled(False)
        start_row.addWidget(self.start_check)
        start_row.addWidget(self.start_edit)
        layout.addLayout(start_row)

        end_row = QHBoxLayout()
        end_row.setSpacing(8)
        self.end_check = QCheckBox("종료 시간", self)
        self.end_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_edit = SectionTimeWidget("00:00:00.00", self)
        self.end_edit.setEnabled(False)
        end_row.addWidget(self.end_check)
        end_row.addWidget(self.end_edit)
        layout.addLayout(end_row)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #ef4444; font-size: 10px; border: none;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.start_check.toggled.connect(self._on_check_toggled)
        self.end_check.toggled.connect(self._on_check_toggled)
        self.start_edit.textChanged.connect(self._validate_inputs)
        self.end_edit.textChanged.connect(self._validate_inputs)

    def set_duration(self, duration: float | None) -> None:
        """영상 전체 길이를 등록하고 종료 시간 기본 텍스트를 갱신합니다."""
        self._duration = max(0.0, float(duration or 0.0))
        if self._duration > 0:
            self.start_edit.set_max_seconds(self._duration)
            self.end_edit.set_max_seconds(self._duration)
            dur_str = format_timestamp(self._duration, use_fraction=True)
            self.end_edit.setText(dur_str)
        else:
            self.start_edit.set_max_seconds(None)
            self.end_edit.set_max_seconds(None)
            self.end_edit.setText("00:00:00.00")

    def _sync_bounds(self) -> None:
        """시작/종료 시간의 상호 경계값을 동기화합니다."""
        start_active = self.start_check.isChecked()
        end_active = self.end_check.isChecked()

        max_sec = self._duration if self._duration > 0 else None
        if end_active and self.end_edit.is_valid_time():
            end_total = self.end_edit.total_seconds()
            max_sec = min(max_sec, end_total) if max_sec is not None else end_total
        self.start_edit.set_max_seconds(max_sec)

        min_sec = 0.0
        if start_active and self.start_edit.is_valid_time():
            min_sec = self.start_edit.total_seconds()
        self.end_edit.set_min_seconds(min_sec)
        self.end_edit.set_max_seconds(self._duration if self._duration > 0 else None)

    def _on_check_toggled(self) -> None:
        """체크박스 토글 시 입력창 활성화 상태를 변경하고 유효성을 재검증합니다."""
        self.start_edit.setEnabled(self.start_check.isChecked())
        self.end_edit.setEnabled(self.end_check.isChecked())
        self._sync_bounds()
        self._validate_inputs()

    def is_valid(self) -> bool:
        """현재 입력된 구간의 유효성을 반환합니다."""
        return self._validate_inputs()

    def _validate_inputs(self) -> bool:
        """현재 입력된 시간의 유효성을 실시간으로 검사하고 피드백을 반영합니다."""
        self._sync_bounds()
        start_active = self.start_check.isChecked()
        end_active = self.end_check.isChecked()

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
        # 이전 경계값에 의해 새 값이 clamp되지 않도록 경계를 일시적으로 전체 길이로 초기화
        self.start_edit.set_max_seconds(self._duration if self._duration > 0 else None)
        self.end_edit.set_min_seconds(0.0)
        self.end_edit.set_max_seconds(self._duration if self._duration > 0 else None)

        if end is not None:
            self.end_check.setChecked(True)
            self.end_edit.set_seconds(end)
        else:
            self.end_check.setChecked(False)

        if start is not None:
            self.start_check.setChecked(True)
            self.start_edit.set_seconds(start)
        else:
            self.start_check.setChecked(False)

        self._sync_bounds()
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
