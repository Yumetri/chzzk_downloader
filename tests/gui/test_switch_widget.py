"""커스텀 토글 스위치 위젯 동작 및 시그널 방출 GUI 테스트."""

import pytest
from PyQt6.QtCore import Qt

from chzzk_downloader.gui.switch_widget import SwitchWidget


@pytest.mark.ticket("T0109")
def test_switch_widget_toggle(qtbot) -> None:
    """[T0109] SwitchWidget 클릭 시 상태 전환 및 toggled 시그널 방출 검증."""
    switch = SwitchWidget(checked=True)
    qtbot.addWidget(switch)
    assert switch.isChecked() is True

    signal_received: list[bool] = []
    switch.toggled.connect(lambda v: signal_received.append(v))

    qtbot.mouseClick(switch, Qt.MouseButton.LeftButton)
    assert switch.isChecked() is False
    assert signal_received == [False]

    switch.setChecked(True)
    assert switch.isChecked() is True
    assert signal_received == [False, True]
