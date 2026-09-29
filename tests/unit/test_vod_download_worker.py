"""VodDownloadWorker 백그라운드 다운로드 작업자 및 옵션 주입 단위 테스트 (T0111 M01.S01.3)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chzzk_downloader.core.task_models import TaskProgress, TaskSpec
from chzzk_downloader.gui.workers import VodDownloadWorker, build_vod_download_opts


@pytest.fixture
def sample_task_spec(tmp_path) -> TaskSpec:
    return TaskSpec(
        task_id="12345",
        video_url="https://chzzk.naver.com/video/12345",
        is_live=False,
        title="테스트 방송 다시보기",
        streamer="치지직스트리머",
        selected_quality="1080p",
        selected_ext="mp4",
        save_path=tmp_path / "test_video.mp4",
    )


def test_build_vod_download_opts_security_and_defense_headers(
    sample_task_spec, tmp_path
):
    """네이버 CDN 400 방어 헤더 및 FFmpeg .m4v 거부 방어 인자가 올바르게 주입되는지 검증."""
    with (
        patch(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_path",
            return_value=Path("C:/fake/ffmpeg.exe"),
        ),
        patch(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_compatible_args",
            return_value=["-extension_picky", "0", "-allowed_extensions", "ALL"],
        ),
        patch(
            "chzzk_downloader.core.cookie_manager.has_valid_cookies",
            return_value=False,
        ),
    ):
        opts = build_vod_download_opts(sample_task_spec)

        # 1. 네이버 CDN 400 방어 헤더 검증
        assert "http_headers" in opts
        assert opts["http_headers"].get("Referer") == "https://chzzk.naver.com/"
        assert "User-Agent" in opts["http_headers"]

        # 2. FFmpeg 바이너리 경로 및 .m4v 거부 방어 인자 검증
        assert opts.get("ffmpeg_location") == "C:/fake/ffmpeg.exe" or Path(
            opts.get("ffmpeg_location")
        ) == Path("C:/fake/ffmpeg.exe")
        assert "postprocessor_args" in opts
        ffmpeg_post_args = opts["postprocessor_args"].get("ffmpeg", [])
        assert "-extension_picky" in ffmpeg_post_args
        assert "0" in ffmpeg_post_args
        assert "-allowed_extensions" in ffmpeg_post_args
        assert "ALL" in ffmpeg_post_args

        # 3. 리먹스 포맷 및 출력 템플릿 검증
        assert opts.get("remuxvideo") == "mp4" or any(
            p.get("key") == "FFmpegVideoRemuxer" and p.get("preferedformat") == "mp4"
            for p in opts.get("postprocessors", [])
        )
        assert str(sample_task_spec.save_path.parent) in opts.get("outtmpl", {}).get(
            "default", str(opts.get("outtmpl", ""))
        )


def test_build_vod_download_opts_with_cookies(sample_task_spec, tmp_path):
    """쿠키가 유효할 경우 cookiefile이 옵션에 포함되는지 검증."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")

    with (
        patch(
            "chzzk_downloader.core.cookie_manager.has_valid_cookies", return_value=True
        ),
        patch(
            "chzzk_downloader.core.cookie_manager.get_cookie_file_path",
            return_value=cookie_file,
        ),
    ):
        opts = build_vod_download_opts(sample_task_spec)
        assert opts.get("cookiefile") == str(cookie_file)


def test_vod_download_worker_successful_flow(sample_task_spec, qtbot):
    """백그라운드 다운로드 정상 완료 시 progress 및 finished 시그널 방출 검증."""
    # 더미 최종 파일 생성
    final_file = Path(sample_task_spec.save_path)
    final_file.parent.mkdir(parents=True, exist_ok=True)

    progress_list: list[TaskProgress] = []
    finished_list: list[tuple[str, str]] = []

    worker = VodDownloadWorker(sample_task_spec)
    worker.progress_updated.connect(progress_list.append)
    worker.download_finished.connect(
        lambda tid, path: finished_list.append((tid, path))
    )

    def mock_download(urls):
        # 다운로드 중 더미 파일 생성
        final_file.write_bytes(b"dummy mp4 video bytes")
        # yt-dlp의 progress_hook 호출 흉내
        for hook in worker._ydl_opts.get("progress_hooks", []):
            hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 500,
                    "total_bytes": 1000,
                    "speed": 1024 * 1024,  # 1 MB/s
                    "eta": 5,
                    "elapsed": 1.0,
                }
            )
            hook(
                {
                    "status": "finished",
                    "downloaded_bytes": 1000,
                    "total_bytes": 1000,
                }
            )
        return 0

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_instance = MagicMock()
        mock_instance.download.side_effect = mock_download
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance

        with qtbot.waitSignal(worker.download_finished, timeout=3000):
            worker.start()

    assert len(finished_list) == 1
    assert finished_list[0][0] == "12345"
    assert Path(finished_list[0][1]).name == final_file.name
    assert len(progress_list) >= 1
    assert progress_list[0].percentage >= 50.0


def test_vod_download_worker_cancellation(sample_task_spec, qtbot):
    """다운로드 중 worker.cancel() 호출 시 download_stopped 시그널이 방출되는지 검증."""
    stopped_list: list[str] = []
    worker = VodDownloadWorker(sample_task_spec)
    worker.download_stopped.connect(stopped_list.append)

    def mock_download(urls):
        # 다운로드 도중 외부에서 cancel 호출
        worker.cancel()
        for hook in worker._ydl_opts.get("progress_hooks", []):
            hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 100,
                    "total_bytes": 1000,
                }
            )
        return 0

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_instance = MagicMock()
        mock_instance.download.side_effect = mock_download
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance

        with qtbot.waitSignal(worker.download_stopped, timeout=3000):
            worker.start()

    assert len(stopped_list) == 1
    assert stopped_list[0] == "12345"


def test_vod_download_worker_error_flow(sample_task_spec, qtbot):
    """yt-dlp 에러 발생 시 download_failed 시그널이 방출되는지 검증."""
    failed_list: list[tuple[str, str, str, str]] = []
    worker = VodDownloadWorker(sample_task_spec)
    worker.download_failed.connect(
        lambda tid, etype, msg, tb: failed_list.append((tid, etype, msg, tb))
    )

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_instance = MagicMock()
        mock_instance.download.side_effect = Exception("403 Forbidden")
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance

        with qtbot.waitSignal(worker.download_failed, timeout=3000):
            worker.start()

    assert len(failed_list) == 1
    assert failed_list[0][0] == "12345"
    assert "403 Forbidden" in failed_list[0][2]


def test_cleanup_partial_files_with_streamer_brackets(tmp_path):
    """결함 2: 치지직 VOD 파일명의 대괄호([스트리머])가 있어도 .part 파일이 정상 삭제되는지 검증."""
    # 치지직 VOD 표준 파일명 포맷: [스트리머] 제목 (video_no).mp4
    save_path = tmp_path / "[침착맨] 삼국지 다시보기 (12345).mp4"
    part_file = tmp_path / "[침착맨] 삼국지 다시보기 (12345).mp4.part"
    part_file.write_bytes(b"temp downloading data")
    ytdl_file = tmp_path / "[침착맨] 삼국지 다시보기 (12345).mp4.ytdl"
    ytdl_file.write_bytes(b"temp ytdl data")

    spec = TaskSpec("12345", "https://chzzk.naver.com/video/12345", save_path=save_path)
    worker = VodDownloadWorker(spec)

    # 취소/실패 시 정리 로직 실행
    worker._cleanup_partial_files()

    assert not part_file.exists(), (
        "대괄호 파일명 패턴에서 .part 파일이 삭제되지 않고 남아있습니다."
    )
    assert not ytdl_file.exists(), (
        "대괄호 파일명 패턴에서 .ytdl 파일이 삭제되지 않고 남아있습니다."
    )


def test_ghost_download_finished_when_file_not_found(tmp_path):
    """결함 7: 다운로드 완료 후 실제 파일이 생성되지 않은 경우 download_finished 대신 download_failed 방출 검증."""
    non_existent_file = tmp_path / "never_created.mp4"
    spec = TaskSpec(
        "123", "https://chzzk.naver.com/video/123", save_path=non_existent_file
    )
    worker = VodDownloadWorker(spec)

    finished_events: list[tuple[str, str]] = []
    failed_events: list[tuple[str, str, str, str]] = []
    worker.download_finished.connect(lambda tid, p: finished_events.append((tid, p)))
    worker.download_failed.connect(lambda *args: failed_events.append(args))

    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_inst = MagicMock()
        mock_inst.download.return_value = 0  # 예외 없이 반환되었으나 파일 미생성
        mock_ydl.return_value.__enter__.return_value = mock_inst

        worker.run()

    assert len(failed_events) > 0, (
        "파일이 존재하지 않는데 download_failed가 방출되지 않았습니다."
    )
    assert len(finished_events) == 0, (
        "존재하지 않는 파일에 대해 download_finished가 오방출되었습니다."
    )


def test_format_speed_edge_cases():
    """결함 9: format_speed의 NaN/Inf 및 GB/s 단위 변환 검증."""
    from chzzk_downloader.gui.workers import format_speed

    assert format_speed(0) == "0.0 KB/s"
    assert format_speed(-10) == "0.0 KB/s"
    assert format_speed(float("nan")) == "0.0 KB/s"
    assert format_speed(float("inf")) == "0.0 KB/s"
    assert format_speed(1024 * 1024) == "1.0 MB/s"
    assert format_speed(1.5 * 1024 * 1024 * 1024) == "1.5 GB/s"
