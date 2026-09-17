# 나만의 미디어 다운로더 GUI 아키텍처 설계 초안
> Hitomi Downloader의 핵심 설계 패턴(엔진 분기, 임시 바이너리 생명주기, 비동기 작업 큐)을 벤치마킹한 구조 가이드

---

## 1. 아키텍처 전체 개요 (High-Level Architecture)

Hitomi Downloader의 가장 큰 장점은 **GUI와 다운로드 엔진이 완전히 분리**되어 있으며, **외부 무거운 도구(FFmpeg, FFprobe, yt-dlp)를 단일 실행 파일 및 임시 경로 격리를 통해 사용자 개입 없이 자동 구동**한다는 점입니다.

`
┌────────────────────────────────────────────────────────────────────────┐
│                          GUI Layer (PyQt6)                             │
│  - MainWindow (URL 입력, 클립보드 감지, 상단 컨트롤)                   │
│  - TaskCard & ListView (작업 카드, 실시간 진행률/속도, 상태 표시)      │
│  - Settings / Cookie Dialog (품질, 경로, 동시 작업 수, 로그인 세션)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Qt Signals / Slots)
┌───────────────────────────────────▼────────────────────────────────────┐
│                    Controller & Task Queue Layer                       │
│  - TaskManager / Queue: 동시 다운로드 수 제한, 우선순위 스케줄링       │
│  - State Machine: QUEUED ➔ EXTRACTING ➔ DOWNLOADING ➔ POST_PROCESSING  │
│  - URL Router: 입력 URL 패턴 분석 후 적절한 엔진으로 라우팅            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Worker Threads / QRunnable)
┌───────────────────────────────────▼────────────────────────────────────┐
│                        Engine & Pipeline Layer                         │
│  ┌───────────────────────┬───────────────────────┬──────────────────┐  │
│  │     yt-dlp Engine     │   FFmpeg Pipeline     │ Multi-thread HTTP│  │
│  │ (동영상 메타데이터/   │ (HLS/M3U8 스트리밍,   │ (정적 이미지,    │  │
│  │  VOD 스트림 추출)     │  영상+오디오 Muxing)  │  대용량 청크 분할)│  │
│  └───────────┬───────────┴───────────┬───────────┴──────────────────┘  │
└──────────────┼───────────────────────┼─────────────────────────────────┘
               │                       │
┌──────────────▼───────────────────────▼─────────────────────────────────┐
│                    System & Dependency Infrastructure                  │
│  - BinaryManager: ffmpeg.exe / ffprobe.exe 자동 탐색, 검증 및 온디맨드 다운로드 │
│  - Storage / Temp: %TEMP% 격리 실행 및 작업 완료 후 임시 파일 청소     │
│  - Settings/DB: 설정 및 다운로드 이력 관리 (SQLite / JSON)             │
└────────────────────────────────────────────────────────────────────────┘
`

---

## 2. 핵심 서브시스템 상세 설계

### 2.1 URL 라우팅 및 엔진 선택 전략 (URL Router)
사용자가 URL을 입력하면 단일 처리기를 거치지 않고 대상 사이트 특성에 맞게 엔진을 선택합니다.

* **동영상 / VOD (YouTube, 치지직 VOD, 트위터 등)**:
  * yt-dlp 파이썬 API (YoutubeDL.extract_info())를 통해 비디오/오디오 스트림 주소 파싱
  * 최고화질 비디오 트랙과 오디오 트랙을 각각 다운로드 후 FFmpeg로 무손실 병합(Muxing)
* **라이브 스트리밍 (치지직 라이브, 트위치 등)**:
  * HLS/M3U8 매니페스트 주소를 획득한 후 FFmpeg에 직접 파이프라인으로 전달하여 실시간 녹화(-c copy)
* **정적 이미지 / 갤러리**:
  * 자체 
equests.Session 기반 멀티스레드 워커 풀(16~32 스레드)로 병렬 다운로드

---

### 2.2 외부 바이너리 생명주기 관리 (BinaryManager)
Hitomi Downloader처럼 **사용자가 FFmpeg를 직접 설치하지 않아도 프로그램이 알아서 해결**하는 구조입니다.

`
[FFmpeg 실행 요청]
       │
       ▼
1. 사용자 지정 경로 (Settings.ffmpeg_path) 확인  ──────(존재)───► [사용]
       │ (없음)
       ▼
2. PyInstaller 임시 번들 디렉터리 (sys._MEIPASS) ───(존재)───► [사용]
       │ (없음)
       ▼
3. 시스템 임시 디렉터리 (%TEMP%/ffmpeg.exe) ─────────(존재)───► [사용]
       │ (없음)
       ▼
4. 앱 실행 폴더 내 ./bin/ffmpeg.exe ────────────────(존재)───► [사용]
       │ (없음)
       ▼
5. 시스템 환경변수 PATH (shutil.which) ─────────────(존재)───► [사용]
       │ (없음)
       ▼
6. [자동 다운로드]: 원격 CDN/GitHub 릴리즈에서
   ffmpeg.exe 및 ffprobe.exe를 백그라운드 다운로드 
   ➔ %TEMP% 또는 %LOCALAPPDATA%에 저장 후 즉시 구동!
`

* **FFprobe의 역할 (검증 및 사전 프로빙)**:
  * 스트림 다운로드 전후에 코덱(h264, hevc, ac 등), 비트레이트, 프레임 손상 여부를 fprobe.exe -show_streams -show_format -of json 명령어로 정밀 진단하여 유효한 영상인지 검증합니다.

---

### 2.3 비동기 작업 큐 및 상태 머신 (Task State Machine)

GUI가 멈추지 않도록(Non-blocking) 모든 다운로드와 변환은 백그라운드 스레드에서 돌아갑니다.

`
 [대기 (QUEUED)]
       │
       ▼
 [정보 추출 (EXTRACTING)]  ──► 실패 시: [오류 (ERROR)] (토스트 알림 및 재시도 버튼)
       │
       ▼
 [다운로드 중 (DOWNLOADING)]
   * 실시간 전송률(MB/s), 진행률(%), 남은 시간(ETA) 시그널 송출
       │
       ▼
 [후처리/병합 (POST_PROCESSING)]
   * FFmpeg Muxing (비디오+오디오 합체) 또는 자막/메타데이터 주입
       │
       ▼
 [완료 (COMPLETED)]
   * 알림 발생, 폴더 열기 / 재생 버튼 활성화
`

---

### 2.4 권장 디렉터리 및 모듈 구조

현재 작업 중이신 chzzk_downloader 프로젝트에 맞춰 확장한 최적의 패키지 구조입니다.

`	ext
chzzk_downloader/
├── src/
│   └── chzzk_downloader/
│       ├── core/                      # 백엔드 핵심 비즈니스 로직
│       │   ├── binary_manager.py      # FFmpeg, FFprobe 자동 탐색/다운로드/버전 검증
│       │   ├── task_manager.py        # 동시 다운로드 제어, 우선순위 큐 관리
│       │   ├── task_state.py          # 작업 상태(Enum), 진행률 데이터클래스
│       │   ├── ytdlp_engine.py        # yt-dlp Python API 래퍼 (VOD 파싱 및 다운로드)
│       │   ├── ffmpeg_engine.py       # FFmpeg 프로세스 파이프라인 (녹화, 병합, 변환)
│       │   ├── cookie_manager.py      # 네이버 로그인 세션 및 쿠키 로드
│       │   ├── settings_manager.py    # 설정 저장 및 영속화 (JSON / SQLite)
│       │   └── url_router.py          # URL 패턴 분석기 (치지직 VOD, 라이브 등 판별)
│       │
│       ├── gui/                       # PyQt6 기반 UI 레이어
│       │   ├── main_window.py         # 메인 프레임, URL 바, 상단 툴바
│       │   ├── task_card.py           # 개별 다운로드 카드 (썸네일, 진행바, 속도, 버튼)
│       │   ├── task_list_view.py      # 작업 카드 스크롤 영역
│       │   ├── settings_dialog.py     # 설정 창 (경로, 화질, 동시 다운로드 수)
│       │   ├── toast.py               # 상태 및 오류 알림 토스트 오버레이
│       │   └── workers.py             # Qt QThread / QRunnable 백그라운드 워커
│       │
│       ├── config.py                  # 전역 상수, 기본값, 타임아웃 정의
│       └── main.py                    # 엔트리포인트 (QApplication 초기화)
│
├── tests/                             # 단위 및 통합 테스트 (pytest)
├── pyproject.toml                     # 프로젝트 의존성 관리 (uv 기반)
└── docs/                              # 설계 및 명세 문서
`

---

## 3. Hitomi Downloader 벤치마킹 핵심 포인트 요약

1. **내장화 vs 경량화의 균형**:
   * yt-dlp는 pyproject.toml을 통해 파이썬 패키지로 앱 내부에 완전히 내장합니다.
   * fmpeg.exe와 fprobe.exe는 exe 용량 비대화(약 150MB+)를 원치 않을 경우, 첫 실행 시 필요할 때 백그라운드에서 자동 다운로드하여 %TEMP%에 캐싱하는 전략을 취할 수 있습니다.
2. **클립보드 자동 감지 (옵션 기능)**:
   * 사용자가 웹 브라우저에서 동영상 링크를 복사하면 프로그램이 이를 감지하여 자동으로 URL 입력칸에 채워주거나 다운로드 카드를 생성하는 편의 기능.
3. **무중단 UI (Graceful Feedback)**:
   * 네트워크 지연이나 FFmpeg 변환 중에도 메인 창이 버벅이지 않도록 모든 입출력은 시그널 기반 이벤트 루프로 격리합니다.
