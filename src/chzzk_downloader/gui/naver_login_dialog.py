"""내장 웹브라우저(QWebEngineView)를 통한 네이버 로그인 다이얼로그 모듈."""

from typing import Any

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.core.cookie_manager import _to_str, save_network_cookies


class NaverLoginDialog(QDialog):
    """네이버 로그인 페이지를 표시하고 로그인 성공 시 쿠키를 자동 추출하는 다이얼로그."""

    login_success = pyqtSignal(str)

    LOGIN_URL = "https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fchzzk.naver.com"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("네이버 로그인")
        self.resize(520, 720)

        self._collected_cookies: dict[str, Any] = {}
        self._is_completed = False

        self._init_ui()
        self._init_webengine()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 상단 안내 영역
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        guide_label = QLabel(
            "치지직 성인 인증 및 비공개 VOD 접근을 위해 네이버에 로그인해 주세요.",
            self,
        )
        guide_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(guide_label)

        self.status_label = QLabel(
            "로그인을 진행해 주세요. 로그인 성공 시 쿠키가 자동으로 감지 및 저장됩니다.",
            self,
        )
        self.status_label.setStyleSheet("font-size: 11px; color: #9ca3af;")
        self.status_label.setWordWrap(True)
        header_layout.addWidget(self.status_label)

        layout.addLayout(header_layout)

        # 웹뷰 영역
        self.webview = QWebEngineView(self)
        layout.addWidget(self.webview, stretch=1)

        # 하단 버튼 영역
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        self.save_btn = QPushButton("로그인 완료 (쿠키 저장)", self)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #03c75a; color: white; border: none; "
            "border-radius: 4px; padding: 6px 14px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #02b150; }"
            "QPushButton:disabled { background-color: #4b5563; color: #9ca3af; }"
        )
        self.save_btn.clicked.connect(self._on_save_and_close)
        bottom_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("닫기", self)
        self.cancel_btn.setStyleSheet(
            "QPushButton { background-color: #374151; color: white; border: none; "
            "border-radius: 4px; padding: 6px 14px; font-size: 12px; }"
            "QPushButton:hover { background-color: #4b5563; }"
        )
        self.cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(self.cancel_btn)

        layout.addLayout(bottom_layout)

    def _init_webengine(self) -> None:
        # 전역 기본 프로필 사용 (종료 시 크래시 방지 및 브라우저 세션 보존)
        prof = QWebEngineProfile.defaultProfile()
        self.profile = prof
        if prof is not None:
            self.cookie_store = prof.cookieStore()
            if self.cookie_store is not None:
                self.cookie_store.cookieAdded.connect(self._on_cookie_added)
            self._webpage = QWebEnginePage(prof, self.webview)
            self.webview.setPage(self._webpage)
        self.webview.urlChanged.connect(self._on_url_changed)
        self.webview.load(QUrl(self.LOGIN_URL))

    def _cleanup(self) -> None:
        """웹뷰 리소스 및 시그널을 안전하게 분리합니다."""
        if getattr(self, "_is_cleaned_up", False):
            return
        self._is_cleaned_up = True

        if hasattr(self, "cookie_store") and self.cookie_store is not None:
            try:
                self.cookie_store.cookieAdded.disconnect(self._on_cookie_added)
            except Exception:
                pass
            self.cookie_store = None

        if hasattr(self, "webview") and self.webview is not None:
            try:
                self.webview.urlChanged.disconnect(self._on_url_changed)
            except Exception:
                pass
            try:
                self.webview.stop()
            except Exception:
                pass

    def reject(self) -> None:
        self._cleanup()
        super().reject()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._cleanup()
        super().closeEvent(event)

    def _on_cookie_added(self, cookie: QNetworkCookie) -> None:
        """쿠키 추가 이벤트 핸들러 - C++ 수명 이슈 방지를 위해 즉시 원시 값으로 복사합니다."""
        try:
            name = _to_str(cookie.name()).strip()
            value = _to_str(cookie.value()).strip()
            domain = _to_str(cookie.domain()).strip()
            path = _to_str(cookie.path()).strip() or "/"
            is_secure = bool(cookie.isSecure())
        except Exception:
            return

        if "naver.com" in domain and name and value:
            self._collected_cookies[name] = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "is_secure": is_secure,
            }

            if name in ("NID_AUT", "NID_SES"):
                found = [
                    k for k in ["NID_AUT", "NID_SES"] if k in self._collected_cookies
                ]
                self.status_label.setText(
                    f"✓ 인증 정보가 감지되었습니다 ({', '.join(found)}). "
                    "자동 완료 대기 중이거나 '로그인 완료'를 눌러 저장하세요."
                )
                self.status_label.setStyleSheet(
                    "font-size: 11px; color: #10b981; font-weight: bold;"
                )
                self.save_btn.setEnabled(True)

    def _on_url_changed(self, url: QUrl) -> None:
        """페이지 이동 시 로그인 완료 여부를 확인합니다."""
        url_str = url.toString()
        has_auth = (
            "NID_AUT" in self._collected_cookies or "NID_SES" in self._collected_cookies
        )

        # nidlogin.login을 벗어나 치지직 또는 네이버 메인으로 리디렉트된 경우 로그인 완료로 판단
        if has_auth and not self._is_completed:
            if "chzzk.naver.com" in url_str or (
                "naver.com" in url_str and "nidlogin" not in url_str
            ):
                self._is_completed = True
                self.status_label.setText(
                    "✓ 로그인 성공! 쿠키를 저장하고 창을 닫습니다..."
                )
                # 사용자에게 성공 메시지를 잠시 보여준 뒤 자동 저장 및 닫기
                QTimer.singleShot(400, self._on_save_and_close)

    def _on_save_and_close(self) -> None:
        """수집된 쿠키를 저장하고 다이얼로그를 완료합니다."""
        if getattr(self, "_is_saved_and_closed", False):
            return

        if not self._collected_cookies:
            QMessageBox.warning(
                self,
                "쿠키 없음",
                "수집된 네이버 쿠키가 없습니다. 로그인을 먼저 진행해 주세요.",
            )
            return

        ok, msg = save_network_cookies(list(self._collected_cookies.values()))
        if ok:
            self._is_saved_and_closed = True
            self._cleanup()
            self.accept()
            self.login_success.emit(msg)
        else:
            QMessageBox.warning(self, "쿠키 저장 실패", msg)
