"""애플리케이션 전역 설정 및 상수."""

from pathlib import Path

# 성공 토스트 자동 소멸 대기 시간 (밀리초 단위, 기본 2초)
SUCCESS_TOAST_DURATION_MS: int = 2000

# 치지직 API 기본 엔드포인트
CHZZK_API_BASE_URL: str = "https://api.chzzk.naver.com"

# 네이버 게임 / 치지직 유저 상태 검증 API 엔드포인트
NAVER_GAME_USER_STATUS_URL: str = (
    "https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus"
)

# 기본 User-Agent
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 기본 쿠키 파일 저장 경로
DEFAULT_COOKIE_FILE_PATH: Path = Path.home() / ".chzzk_downloader" / "cookies.txt"

# 기본 설정 파일 저장 경로 (T0108)
DEFAULT_SETTINGS_FILE_PATH: Path = Path.home() / ".chzzk_downloader" / "settings.json"

# 기본 다운로드 디렉터리 이름 (T0108)
DEFAULT_DOWNLOAD_DIR_NAME: str = "chzzk_downloaded"

# 선택 가능한 기본 화질 목록 (T0108)
AVAILABLE_QUALITIES: tuple[str, ...] = ("최고 화질", "1080p", "720p", "480p", "360p")

# 선택 가능한 기본 파일 확장자 목록 (T0108)
AVAILABLE_EXTENSIONS: tuple[str, ...] = (".mp4", ".ts")
