"""오류 분류 단일화(classify_error) 단위 테스트.

숫자 부분문자열 오분류(D04) 방지 및 단일 오류 분류기 규격을 검증합니다.
"""

from chzzk_downloader.core.errors import classify_error
from chzzk_downloader.core.task_models import TaskStatus


def test_classify_error_http_500_with_19_in_video_url_is_failed_download():
    """video_no에 19가 포함된 URL의 HTTP 500 오류는 FAILED_LOGIN_REQUIRED가 아닌 FAILED_DOWNLOAD로 분류되어야 한다."""
    url = "https://chzzk.naver.com/video/1190452"
    msg = f"HTTP Error 500: Internal Server Error for {url}"
    status = classify_error(exc_type="DownloadError", msg=msg)
    assert status == TaskStatus.FAILED_DOWNLOAD


def test_classify_error_oserror_with_cert_path_is_failed_download():
    """경로에 '인증서'가 포함된 OSError는 FAILED_LOGIN_REQUIRED가 아닌 FAILED_DOWNLOAD로 분류되어야 한다."""
    msg = "[Errno 2] No such file or directory: 'C:/Users/test/인증서/client.crt'"
    status = classify_error(exc_type="OSError", msg=msg)
    assert status == TaskStatus.FAILED_DOWNLOAD


def test_classify_error_ffmpeg_invalid_data_is_failed_download():
    """FFmpeg의 'Invalid data found' 오류는 FAILED_INVALID가 아닌 FAILED_DOWNLOAD로 분류되어야 한다."""
    msg = "ffmpeg exited with code 1: Invalid data found when processing input"
    status = classify_error(exc_type="DownloadError", msg=msg)
    assert status == TaskStatus.FAILED_DOWNLOAD


def test_classify_error_http_status_codes():
    """HTTP 상태 코드에 따른 정확한 상태 매핑을 검증한다."""
    # 401, 403 -> 로그인/인증 필요
    assert (
        classify_error(exc_type="HTTPError", msg="HTTP Error 401: Unauthorized")
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )
    assert (
        classify_error(
            exc_type="DownloadError",
            msg="HTTP Error 403: Forbidden for video 4031234",
        )
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )
    assert (
        classify_error(msg="Generic error", http_status=401)
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )
    assert (
        classify_error(msg="Generic error", http_status=403)
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )

    # 404 -> 잘못된/삭제된 URL
    assert (
        classify_error(exc_type="HTTPError", msg="HTTP Error 404: Not Found")
        == TaskStatus.FAILED_INVALID
    )
    assert (
        classify_error(msg="Generic error", http_status=404)
        == TaskStatus.FAILED_INVALID
    )

    # 5xx -> 일반 다운로드 실패
    assert (
        classify_error(exc_type="HTTPError", msg="HTTP Error 503: Service Unavailable")
        == TaskStatus.FAILED_DOWNLOAD
    )
    assert (
        classify_error(msg="Generic error", http_status=500)
        == TaskStatus.FAILED_DOWNLOAD
    )


def test_classify_error_adult_and_login_keywords():
    """성인 및 로그인 필요 키워드에 대한 매핑을 검증한다."""
    assert (
        classify_error(msg="성인 인증이 필요한 영상입니다.")
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )
    assert (
        classify_error(msg="Login required to access this 19+ video")
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )
    assert (
        classify_error(exc_type="LoginRequiredError", msg="로그인이 필요합니다.")
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )


def test_classify_error_not_found_and_private_keywords():
    """비공개 및 리소스 미존재 키워드에 대한 매핑을 검증한다."""
    assert classify_error(msg="비공개 동영상입니다.") == TaskStatus.FAILED_INVALID
    assert (
        classify_error(exc_type="VodNotFoundError", msg="존재하지 않는 동영상입니다.")
        == TaskStatus.FAILED_INVALID
    )
    assert classify_error(msg="잘못된 URL 형식입니다.") == TaskStatus.FAILED_INVALID


def test_classify_error_unclassified_is_failed_download():
    """분류되지 않은 임의의 런타임 오류는 FAILED_DOWNLOAD로 안전하게 수렴해야 한다."""
    assert (
        classify_error(exc_type="RuntimeError", msg="Connection reset by peer")
        == TaskStatus.FAILED_DOWNLOAD
    )


def test_classify_error_adult_video_with_cert_title_should_be_login_required():
    """영상 제목 등에 '인증서'가 포함되어도 로그인/성인인증 필요 오류는 FAILED_LOGIN_REQUIRED로 분류되어야 한다."""
    msg = "[Chzzk] 12345 (자격증/인증서 취득 특강): 성인 인증이 필요한 영상입니다."
    assert (
        classify_error(exc_type="LoginRequiredError", msg=msg)
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )


def test_classify_error_age_restricted_and_19gum_keywords():
    """'연령 제한', '19금', '본인 인증' 등의 표현도 FAILED_LOGIN_REQUIRED로 정확히 분류되어야 한다."""
    assert (
        classify_error(msg="연령 제한 동영상입니다.")
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )
    assert classify_error(msg="19금 동영상입니다.") == TaskStatus.FAILED_LOGIN_REQUIRED
    assert (
        classify_error(msg="본인 인증이 필요합니다.")
        == TaskStatus.FAILED_LOGIN_REQUIRED
    )


def test_classify_error_http_status_regex_boundaries():
    """HTTP 3자리 코드 뒤에 숫자가 이어지는 경우 임의로 잘라 매칭하지 않아야 하며, 일반 HTTP 404/410 형식도 인식해야 한다."""
    # 5자리 내부 에러 코드가 404로 오인식되지 않아야 함
    assert (
        classify_error(msg="HTTP Error 40401: Service internal code")
        == TaskStatus.FAILED_DOWNLOAD
    )

    # 'Error' 단어가 생략된 HTTP 404도 FAILED_INVALID로 분류되어야 함
    assert classify_error(msg="Server returned HTTP 404") == TaskStatus.FAILED_INVALID

    # HTTP 410 (Gone)도 FAILED_INVALID로 분류되어야 함
    assert classify_error(msg="HTTP Error 410: Gone") == TaskStatus.FAILED_INVALID
