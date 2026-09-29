# 치지직 다운로더 (Chzzk Downloader)

> 네이버 치지직(Chzzk) VOD 동영상을 최고 화질로 간편하게 다운로드할 수 있는 고신뢰성 데스크톱 GUI 애플리케이션입니다.

---

## 주요 기능

- **초간단 다운로드**: 치지직 VOD URL만 입력창에 붙여넣으면 즉시 메타데이터 분석 및 다운로드 준비
- **최고 화질 무손실 병합**: 비디오와 오디오 스트림을 최적 분리 다운로드 후 FFmpeg 기반 무손실 Muxing
- **FFmpeg 자동 관리**: 시스템에 FFmpeg가 없어도 앱 자체에서 안전하게 탐색 및 온디맨드 자동 구성
- **네이버 로그인 세션 지원**: 성인 인증 또는 연령 제한 VOD를 위한 내장 네이버 웹뷰 로그인 및 쿠키 연동
- **세련된 다크 테마 GUI**: Hitomi Downloader의 콤팩트한 4분면 카드 레이아웃과 치지직 시그니처 네온 포인트 적용

---

## 실행 방법

본 프로젝트는 [uv](https://docs.astral.sh/uv/) 패키지 관리자를 기반으로 구동됩니다.

### 1. 의존성 동기화
```bash
uv sync
```

### 2. GUI 애플리케이션 실행
```bash
uv run python -m chzzk_downloader.main
```

---

## 개발자 가이드 및 아키텍처

AI 에이전트 개발 지침, 4대 동시성 방어 규칙, TDD 워크플로우 및 코드 품질 검사(Ruff, Pyrefly, Pytest) 명령어는 아래 단일 진실 공급원(SSOT) 문서를 참조하십시오:

- 📖 **중앙 개발 관제탑**: [`AGENTS.md`](AGENTS.md)
- 🎨 **UI 피드백 규격서**: [`docs/UI_FEEDBACK_CATALOG.md`](docs/UI_FEEDBACK_CATALOG.md)
- 🛡️ **적대적 검증 가이드**: [`docs/AI_ADVERSARIAL_VALIDATOR_GUIDE.md`](docs/AI_ADVERSARIAL_VALIDATOR_GUIDE.md)
