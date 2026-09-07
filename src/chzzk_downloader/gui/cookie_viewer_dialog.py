"""쿠키 보기 및 직접 입력 모달 다이얼로그 (T0106)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.core.cookie_manager import (
    get_cookies_text,
    save_cookies_text,
)


class CookieViewerDialog(QDialog):
    """저장된 쿠키를 확인하고 직접 편집/입력할 수 있는 모달 다이얼로그."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("쿠키 보기 및 직접 입력")
        self.resize(560, 420)
        self.setModal(True)

        self._init_ui()
        self._load_current_cookies()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 1. 친절한 안내 가이드 라벨
        guide_label = QLabel(
            "<b>치지직 성인 인증 및 비공개/구독 VOD 조회를 위해 네이버 로그인 쿠키가 필요합니다.</b><br>"
            "<span style='color: #9ca3af; font-size: 11px;'>"
            "• 지원 형식: <code>NID_AUT=...; NID_SES=...</code> (F12 개발자 도구 &gt; Application &gt; Cookies 복사값)<br>"
            "• 또는 Netscape HTTP Cookie Files (<code># Netscape HTTP Cookie File...</code>) 형식<br>"
            "• <b>필수 항목:</b> <code>NID_AUT</code> 또는 <code>NID_SES</code>가 반드시 포함되어야 합니다."
            "</span>",
            self,
        )
        guide_label.setTextFormat(Qt.TextFormat.RichText)
        guide_label.setWordWrap(True)
        layout.addWidget(guide_label)

        # 2. 텍스트 에디터 영역
        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlaceholderText(
            "여기에 쿠키 문자열 또는 Netscape 쿠키 파일 내용을 붙여넣으세요.\n\n"
            "예시 (헤더 문자열):\n"
            "NID_AUT=xxxxxx; NID_SES=yyyyyy\n\n"
            "예시 (Netscape txt):\n"
            ".naver.com\tTRUE\t/\tFALSE\t2147483647\tNID_AUT\txxxxxx\n"
            ".naver.com\tTRUE\t/\tFALSE\t2147483647\tNID_SES\tyyyyyy"
        )
        self.text_edit.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #1e1e1e;"
            "  color: #e0e0e0;"
            "  border: 1px solid #333333;"
            "  border-radius: 4px;"
            "  font-family: Consolas, monospace;"
            "  font-size: 12px;"
            "  padding: 6px;"
            "}"
        )
        layout.addWidget(self.text_edit, stretch=1)

        # 3. 유효성 피드백 라벨
        self.feedback_label = QLabel("", self)
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 11px;")
        self.feedback_label.hide()
        layout.addWidget(self.feedback_label)

        # 4. 버튼 영역
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("취소", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("저장", self)
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.save_btn.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

    def _load_current_cookies(self) -> None:
        """현재 저장되어 있는 쿠키 텍스트를 불러와 표시합니다."""
        text = get_cookies_text()
        if text:
            self.text_edit.setPlainText(text)

    def _on_save_clicked(self) -> None:
        """사용자가 입력한 쿠키를 검증하고 저장합니다."""
        text = self.text_edit.toPlainText().strip()
        ok, msg = save_cookies_text(text)
        if ok:
            self.accept()
        else:
            self.feedback_label.setText(f"❌ {msg}")
            self.feedback_label.setStyleSheet(
                "color: #ef4444; font-size: 12px; font-weight: bold;"
            )
            self.feedback_label.show()
