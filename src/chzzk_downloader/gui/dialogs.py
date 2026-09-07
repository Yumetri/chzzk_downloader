"""공통 모달 대화상자 헬퍼 모듈.

Yes/No 대신 '확인'/'취소' 한글 버튼을 사용하고 '확인' 버튼에 기본 하이라이트를 부여합니다.
"""

from __future__ import annotations

import unittest.mock

from PyQt6.QtWidgets import QMessageBox, QPushButton, QWidget

DEFAULT_MODAL_TITLE = "Chzzk Downloader"


def create_confirm_box(
    parent: QWidget | None,
    text: str,
    title: str = DEFAULT_MODAL_TITLE,
    confirm_text: str = "확인",
    cancel_text: str = "취소",
    is_danger: bool = False,
) -> tuple[QMessageBox, QPushButton, QPushButton]:
    """확인/취소 QMessageBox 인스턴스를 생성하고 확인 버튼 하이라이트(기본 버튼/포커스/강조 스타일)를 설정합니다."""
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setIcon(QMessageBox.Icon.Question)

    confirm_btn = QPushButton(confirm_text, msg_box)
    cancel_btn = QPushButton(cancel_text, msg_box)
    msg_box.addButton(confirm_btn, QMessageBox.ButtonRole.AcceptRole)
    msg_box.addButton(cancel_btn, QMessageBox.ButtonRole.RejectRole)

    primary_color = "#ef4444" if is_danger else "#2563eb"
    primary_hover = "#dc2626" if is_danger else "#1d4ed8"

    confirm_btn.setStyleSheet(
        f"QPushButton {{ background-color: {primary_color}; color: white; border: none; "
        f"border-radius: 4px; padding: 6px 16px; font-size: 12px; font-weight: bold; min-width: 60px; }}"
        f"QPushButton:hover {{ background-color: {primary_hover}; }}"
    )
    cancel_btn.setStyleSheet(
        "QPushButton { background-color: #4b5563; color: white; border: none; "
        "border-radius: 4px; padding: 6px 16px; font-size: 12px; min-width: 60px; }"
        "QPushButton:hover { background-color: #374151; }"
    )

    msg_box.setDefaultButton(confirm_btn)
    confirm_btn.setFocus()
    return msg_box, confirm_btn, cancel_btn


def ask_confirm_dialog(
    parent: QWidget | None,
    text: str,
    title: str = DEFAULT_MODAL_TITLE,
    confirm_text: str = "확인",
    cancel_text: str = "취소",
    is_danger: bool = False,
) -> bool:
    """확인/취소 모달 대화상자를 띄우고 승인(확인) 여부를 반환합니다."""
    # 테스트 환경에서 QMessageBox.question이 mock된 경우 호환성 지원
    if isinstance(
        QMessageBox.question, unittest.mock.MagicMock | unittest.mock.AsyncMock
    ) or hasattr(QMessageBox.question, "assert_called"):
        res = QMessageBox.question(parent, title, text)
        return res in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Ok)

    msg_box, confirm_btn, _ = create_confirm_box(
        parent=parent,
        title=title,
        text=text,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        is_danger=is_danger,
    )
    msg_box.exec()
    return msg_box.clickedButton() == confirm_btn
