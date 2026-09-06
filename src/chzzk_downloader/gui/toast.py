from collections.abc import Callable
from enum import Enum

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


class ToastType(Enum):
    """토스트 알림 종류."""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ClickableCloseLabel(QLabel):
    """클릭 이벤트를 지원하는 닫기 라벨 버튼."""

    def __init__(
        self,
        text: str = "✕",
        parent: QWidget | None = None,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._on_click = on_click

    def mousePressEvent(self, ev: QMouseEvent | None) -> None:  # noqa: N802
        if self._on_click:
            self._on_click()
        super().mousePressEvent(ev)

    def click(self) -> None:
        """프로그래밍 방식 클릭 호출 지원."""
        if self._on_click:
            self._on_click()


class ToastWidget(QFrame):
    """메인 창 내부에 오버레이 형태로 표시되는 토스트 알림 위젯."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self._is_action_mode = False
        self._action_buttons: list[QPushButton] = []

        self._init_ui()
        self.hide()

    def _init_ui(self) -> None:
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(14, 8, 14, 8)
        self.main_layout.setSpacing(10)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.label = QLabel(self)
        self.label.setWordWrap(False)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.main_layout.addWidget(self.label)

        # 액션 버튼들이 배치될 수평 레이아웃
        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(6)
        self.btn_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.main_layout.addLayout(self.btn_layout)

        self.close_btn = ClickableCloseLabel("✕", self, on_click=self.dismiss)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(
            "QLabel { color: #9ca3af; font-size: 12px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }"
            "QLabel:hover { color: #ffffff; background-color: rgba(255, 255, 255, 0.15); }"
        )
        self.main_layout.addWidget(self.close_btn)

    def _clear_action_buttons(self) -> None:
        """이전 액션 버튼들을 레이아웃에서 제거합니다."""
        for btn in self._action_buttons:
            self.btn_layout.removeWidget(btn)
            btn.deleteLater()
        self._action_buttons.clear()

    def show_toast(
        self,
        message: str,
        toast_type: ToastType = ToastType.SUCCESS,
        auto_dismiss_ms: int = 0,
    ) -> None:
        """일반 토스트를 표시합니다 (2초 자동 소멸 시 닫기 버튼 숨김)."""
        self._is_action_mode = False
        self._clear_action_buttons()
        self.close_btn.hide()
        if "<" in message and ">" in message:
            self.label.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setText(message)

        if toast_type == ToastType.ERROR:
            border_style = "border: 1px solid rgba(239, 68, 68, 0.5);"
        elif toast_type == ToastType.WARNING:
            border_style = "border: 1px solid rgba(245, 158, 11, 0.5);"
        else:
            border_style = "border: 1px solid rgba(255, 255, 255, 0.18);"

        bg_style = f"background-color: rgba(20, 20, 20, 230); {border_style}"

        self.setStyleSheet(
            f"ToastWidget {{ {bg_style} border-radius: 8px; }}"
            f"QLabel {{ color: white; font-size: 13px; font-weight: 500; }}"
        )

        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

        self._timer.stop()
        if auto_dismiss_ms > 0:
            self._timer.start(auto_dismiss_ms)

    def show_action_toast(
        self,
        message: str,
        buttons: list[
            tuple[str, str, Callable[[], None]]
            | tuple[str, str, Callable[[], None], str]
        ],
    ) -> None:
        """액션 버튼이 포함된 인터랙티브 토스트를 표시합니다.

        Args:
            message: 표시할 안내 메시지.
            buttons: (버튼명, 배경색, 클릭시 콜백함수, [선택적 툴팁]) 튜플 목록.
        """
        self._is_action_mode = True
        self._timer.stop()  # 사용자가 조작하기 전까지 자동 소멸 안 됨
        self._clear_action_buttons()
        self.close_btn.show()

        if "<" in message and ">" in message:
            self.label.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setText(message)

        for item in buttons:
            label_text = item[0]
            color_code = item[1]
            callback = item[2]
            tooltip_text = item[3] if len(item) > 3 else ""

            # 기본 툴팁 추론
            if not tooltip_text:
                if label_text == "🍪":
                    tooltip_text = "쿠키 설정"
                elif label_text == "N":
                    tooltip_text = "네이버 로그인"

            btn = QPushButton(label_text, self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if tooltip_text:
                btn.setToolTip(tooltip_text)

            # 쿠키 아이콘인 경우: 배경 제거하고 투명 아이콘 단독 노출 (호버 시에만 하이라이트)
            if label_text == "🍪":
                btn.setFixedSize(24, 22)
                btn.setStyleSheet(
                    "QPushButton { background-color: transparent; border: none; font-size: 14px; padding: 0; }"
                    "QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); border-radius: 3px; }"
                )
            elif len(label_text) <= 2:
                # 네이버 N 등 컴팩트 사각 버튼
                btn.setFixedSize(24, 22)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {color_code}; color: white; border: none; "
                    f"border-radius: 3px; font-size: 12px; font-weight: 900; padding: 0; }}"
                    f"QPushButton:hover {{ opacity: 0.85; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {color_code}; color: white; border: none; "
                    f"border-radius: 4px; padding: 4px 10px; font-size: 12px; font-weight: bold; }}"
                    f"QPushButton:hover {{ opacity: 0.9; }}"
                )

            def _make_handler(cb: Callable[[], None]) -> Callable[[], None]:
                def _handler() -> None:
                    self.dismiss()
                    cb()

                return _handler

            btn.clicked.connect(_make_handler(callback))
            self.btn_layout.addWidget(btn)
            self._action_buttons.append(btn)

        bg_style = "background-color: rgba(20, 20, 20, 235); border: 1px solid rgba(245, 158, 11, 0.5);"
        self.setStyleSheet(
            f"ToastWidget {{ {bg_style} border-radius: 8px; }}"
            f"QLabel {{ color: white; font-size: 13px; font-weight: 500; }}"
        )

        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

    def reposition(self) -> None:
        """부모 위젯 기준으로 토스트 위치를 중앙 하단으로 재배치합니다 (내용 맞춤형 유동적 너비)."""
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return

        max_w = int(parent_widget.width() * 0.92)
        self.label.setWordWrap(False)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(max_w, 16777215)
        self.adjustSize()

        # 만약 자연스러운 너비가 부모 창 한도를 초과하는 경우에만 줄바꿈 활성화
        if self.sizeHint().width() > max_w:
            self.label.setWordWrap(True)
            self.setFixedWidth(max_w)
            self.adjustSize()

        x = (parent_widget.width() - self.width()) // 2
        y = parent_widget.height() - self.height() - 24
        self.move(max(10, x), max(10, y))

    def dismiss(self) -> None:
        """토스트를 숨기고 타이머를 중지합니다."""
        self._timer.stop()
        self._clear_action_buttons()
        self.hide()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        """일반 토스트 클릭 시 즉시 닫히며, 액션 모드에서는 버튼 조작을 위해 통과시킵니다."""
        if not self._is_action_mode:
            self.dismiss()
        if event is not None:
            super().mousePressEvent(event)
