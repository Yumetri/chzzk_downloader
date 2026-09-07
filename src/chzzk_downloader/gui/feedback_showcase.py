"""UI 피드백(모달 및 토스트) 인터랙티브 쇼케이스 도구.

개발자가 프로그램의 모든 모달 대화상자와 토스트 알림을 한 자리에서 직접 띄워보며
디자인, 여백, 폰트, 문체, 하이라이트 및 버튼 인터랙션을 즉각 검증할 수 있는 개발용 도구입니다.

실행 방법:
    uv run python -m chzzk_downloader.gui.feedback_showcase
또는
    uv run python tools/preview_ui_feedbacks.py
"""

from __future__ import annotations

import sys
from typing import Any

from PyQt6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.gui.dialogs import ask_confirm_dialog
from chzzk_downloader.gui.toast import ToastType, ToastWidget


class FeedbackShowcaseWindow(QMainWindow):
    """모달과 토스트를 한눈에 확인하고 테스트할 수 있는 프리뷰어 창."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(
            "치지직 다운로더 - UI 피드백 쇼케이스 (모달 & 토스트 갤러리)"
        )
        self.resize(880, 720)

        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # 상단 타이틀 안내
        header_label = QLabel(
            "🎨 UI 피드백 쇼케이스\n버튼을 클릭하여 각 모달 대화상자와 토스트의 문체, 디자인, 버튼 하이라이트를 즉각 확인하세요.",
            self,
        )
        header_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #1f2937;"
        )
        root_layout.addWidget(header_label)

        # 본문 좌/우 2열 레이아웃
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(16)

        # 좌측: 토스트 테스트 영역
        toast_group = QGroupBox("🍞 토스트 알림 (Toast Notifications)", self)
        toast_group.setStyleSheet("font-weight: bold; font-size: 13px;")
        toast_layout = QVBoxLayout(toast_group)
        toast_layout.setSpacing(8)

        self._add_btn(
            toast_layout,
            "[T01] URL 추가 안내 토스트",
            self._demo_toast_add_url,
            "#2563eb",
        )
        self._add_btn(
            toast_layout,
            "[T02] 쿠키 재분석 안내 토스트 (초록 성공)",
            self._demo_toast_reanalyze_success,
            "#059669",
        )
        self._add_btn(
            toast_layout,
            "[T03] 진행중 중복 거부 토스트 (2초 소멸)",
            self._demo_toast_duplicate_rejected,
            "#dc2626",
        )
        self._add_btn(
            toast_layout,
            "[T04] 지원하지 않는 URL 실패 토스트",
            self._demo_toast_unsupported_url,
            "#dc2626",
        )
        self._add_btn(
            toast_layout,
            "[T05] VOD 확인 실패 오류 토스트",
            self._demo_toast_vod_check_failed,
            "#dc2626",
        )
        self._add_btn(
            toast_layout,
            "[T06] 쿠키 만료 경고 액션 토스트 (버튼 포함)",
            self._demo_toast_cookie_expired_action,
            "#d97706",
        )
        toast_layout.addStretch()
        columns_layout.addWidget(toast_group, 1)

        # 우측: 모달 대화상자 테스트 영역
        modal_group = QGroupBox("💬 모달 대화상자 (Modal Dialogs)", self)
        modal_group.setStyleSheet("font-weight: bold; font-size: 13px;")
        modal_layout = QVBoxLayout(modal_group)
        modal_layout.setSpacing(8)

        self._add_btn(
            modal_layout,
            "[M01] 다운로드 중지 확인 모달 (확인 하이라이트)",
            self._demo_modal_stop_download,
            "#1d4ed8",
        )
        self._add_btn(
            modal_layout,
            "[M02] 작업 재다운로드 확인 모달 (확인 하이라이트)",
            self._demo_modal_redownload_duplicate,
            "#1d4ed8",
        )
        self._add_btn(
            modal_layout,
            "[M03] 쿠키 초기화 확인 모달 (Danger 빨간 하이라이트)",
            self._demo_modal_clear_cookie,
            "#b91c1c",
        )
        self._add_btn(
            modal_layout,
            "[M04] 파일 중복 충돌 선택 모달 (덮어쓰기/이름변경/취소)",
            self._demo_modal_file_conflict,
            "#4b5563",
        )
        self._add_btn(
            modal_layout,
            "[M05/M06] 쿠키 불러오기/내보내기 완료 안내 모달",
            self._demo_modal_cookie_info,
            "#4b5563",
        )
        self._add_btn(
            modal_layout,
            "[M07] 폴더 권한 오류 경고 모달",
            self._demo_modal_folder_error,
            "#b45309",
        )
        modal_layout.addStretch()
        columns_layout.addWidget(modal_group, 1)

        root_layout.addLayout(columns_layout, 1)

        # 하단: 결과 로그 콘솔
        log_group = QGroupBox("📋 피드백 실행 로그 및 결과", self)
        log_layout = QVBoxLayout(log_group)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(120)
        self.log_edit.setStyleSheet(
            "background-color: #111827; color: #10b981; font-family: monospace; font-size: 12px;"
        )
        log_layout.addWidget(self.log_edit)
        root_layout.addWidget(log_group)

        # 토스트 위젯 오버레이 탑재
        self.toast = ToastWidget(self)
        self._log(
            "쇼케이스가 준비되었습니다. 원하는 토스트 또는 모달 버튼을 클릭하세요."
        )

    def _add_btn(
        self,
        layout: QVBoxLayout,
        text: str,
        slot: Any,
        bg_color: str = "#374151",
    ) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg_color}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 14px; font-size: 12px; text-align: left; }}"
            f"QPushButton:hover {{ background-color: #4b5563; }}"
        )
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        return btn

    def _log(self, msg: str) -> None:
        self.log_edit.append(f"• {msg}")

    # --- 토스트 데모 메서드 ---
    def _demo_toast_add_url(self) -> None:
        self._log("[T01] URL 추가 토스트 호출 (2초 자동 소멸)")
        msg = (
            '<span style="color: #3b82f6; font-weight: bold; font-size: 14px;">+</span> '
            '<span style="color: #ffffff;">https://chzzk.naver.com/video/15016450</span>'
        )
        self.toast.show_toast(msg, ToastType.SUCCESS, auto_dismiss_ms=2000)

    def _demo_toast_reanalyze_success(self) -> None:
        self._log("[T02] 쿠키 재분석 안내 토스트 호출 (2초 자동 소멸)")
        self.toast.show_toast(
            "쿠키가 등록되어 로그인 필요 작업을 다시 분석합니다.",
            ToastType.SUCCESS,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_duplicate_rejected(self) -> None:
        self._log("[T03] 진행중 중복 거부 토스트 호출 (2초 자동 소멸)")
        self.toast.show_toast(
            "이미 추가한 작업입니다.",
            ToastType.ERROR,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_unsupported_url(self) -> None:
        self._log("[T04] 지원하지 않는 URL 실패 토스트 호출 (수동 닫기/새요청 시 소멸)")
        self.toast.show_toast(
            "지원하지 않는 URL",
            ToastType.ERROR,
        )

    def _demo_toast_vod_check_failed(self) -> None:
        self._log("[T05] VOD 확인 실패 토스트 호출 (수동 닫기/새요청 시 소멸)")
        self.toast.show_toast(
            "VOD 확인 실패: 비디오를 찾을 수 없거나 비공개 영상입니다.",
            ToastType.ERROR,
        )

    def _demo_toast_cookie_expired_action(self) -> None:
        self._log("[T06] 쿠키 만료 경고 인터랙티브 액션 토스트 호출")
        self.toast.show_action_toast(
            "저장된 네이버 쿠키가 만료되었습니다.",
            buttons=[
                (
                    "쿠키 설정",
                    "#374151",
                    lambda: self._log("액션 토스트: [쿠키 설정] 클릭됨"),
                ),
                (
                    "네이버 로그인",
                    "#03c75a",
                    lambda: self._log("액션 토스트: [네이버 로그인] 클릭됨"),
                ),
            ],
        )

    # --- 모달 데모 메서드 ---
    def _demo_modal_stop_download(self) -> None:
        self._log("[M01] 다운로드 중지 확인 모달 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="정말 중지하시겠습니까?",
        )
        self._log(
            f"[M01] 다운로드 중지 결과: {'[확인] 승인됨 (다운로드 중단)' if ok else '[취소] 거부됨 (다운로드 유지)'}"
        )

    def _demo_modal_redownload_duplicate(self) -> None:
        self._log("[M02] 작업 재다운로드 확인 모달 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="이미 추가한 작업입니다. 다시 다운로드하시겠습니까?",
        )
        self._log(
            f"[M02] 재다운로드 결과: {'[확인] 승인됨 (클린 리셋 재시작)' if ok else '[취소] 거부됨 (기존 카드 유지)'}"
        )

    def _demo_modal_clear_cookie(self) -> None:
        self._log("[M03] 쿠키 초기화 확인 모달 (Danger 빨간 강조) 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="저장된 쿠키를 삭제하시겠습니까?",
            is_danger=True,
        )
        self._log(
            f"[M03] 쿠키 초기화 결과: {'[확인] 승인됨 (쿠키 삭제 실행)' if ok else '[취소] 거부됨'}"
        )

    def _demo_modal_file_conflict(self) -> None:
        self._log("[M04] 파일명 중복 충돌 모달 (3선택 분기) 호출 대기...")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Chzzk Downloader")
        msg_box.setText(
            "이미 동일한 이름의 파일이 존재합니다:\n[스트리머A] 2026-09-06 방송.mp4\n\n어떻게 처리하시겠습니까?"
        )
        overwrite_btn = msg_box.addButton("덮어쓰기", QMessageBox.ButtonRole.AcceptRole)
        rename_btn = msg_box.addButton("이름 변경", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(rename_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == overwrite_btn:
            choice = "덮어쓰기"
        elif clicked == rename_btn:
            choice = "이름 변경 (1 추가)"
        else:
            choice = "취소"
        self._log(f"[M04] 파일 중복 선택 결과: [{choice}]")

    def _demo_modal_cookie_info(self) -> None:
        self._log("[M05/M06] 쿠키 안내 모달 호출")
        QMessageBox.information(
            self,
            "Chzzk Downloader",
            "쿠키 파일에서 2개의 쿠키를 성공적으로 불러왔습니다.",
        )
        self._log("[M05/M06] 안내 모달 닫힘")

    def _demo_modal_folder_error(self) -> None:
        self._log("[M07] 폴더 권한 오류 경고 모달 호출")
        QMessageBox.warning(
            self,
            "Chzzk Downloader",
            "선택한 폴더에 쓰기 권한이 없습니다:\nC:\\System\\Restricted\n\n다른 폴더를 선택해주세요.",
        )
        self._log("[M07] 경고 모달 닫힘")


def main() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = FeedbackShowcaseWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
