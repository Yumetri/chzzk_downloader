# Hitomi Downloader 기반 치지직 핵심 기능 및 UI/UX 디자인 규격서
> **목적**: `hitomi_downloader_GUI.exe`의 방대한 기능 중 **치지직(Chzzk) 실시간 녹화, VOD 다운로드, 자동 녹화 모니터링, 알림 체계**와 **UI/UX 디자인·설정 사양**만을 정밀 추출하여, AI Agent가 즉시 이해하고 구현에 착수할 수 있도록 정형화한 개발 참조 규격서입니다. (백엔드 기본 아키텍처는 `DOWNLOADER_GUI_ARCHITECTURE.md` 참조)

---

## 1. 벤치마크 개요 및 추출 범위

| 구분 | Hitomi Downloader 원본 사양 | 치지직 다운로더 경량화 사양 |
| :--- | :--- | :--- |
| **타깃 플랫폼** | 수백 개 사이트 (이미지 갤러리, 웹툰, 만화, 동영상 등) | **치지직(Chzzk) 단일 플랫폼 특화** (VOD & Live) |
| **다운로드 엔진** | 멀티스레드 HTTP 청크, yt-dlp, FFmpeg, BitTorrent 등 혼재 | **yt-dlp (VOD 메타데이터/다운로드) + FFmpeg 파이프라인 (실시간 무손실 Muxing)** |
| **주요 추출 대상** | 1) 치지직 실시간 녹화 & 자동 채널 감시 파라미터<br>2) VOD 화질/코덱/파일명 규칙<br>3) 알림, 트레이, 절전모드 방지 시스템<br>4) 4분면 작업 카드 레이아웃, 단축키, 에러 진단 팝업 | 동일 기능의 경량 구현 + 치지직 UX 최적화 |
| **제외 대상** | 이미지 갤러리 뷰어, 토렌트 시딩, 만화 태그 검색기, 불필요한 외부 사이트 파서 | 완전 배제하여 실행 파일 및 메모리 점유율 극소화 |

---

## 2. 핵심 기능별 환경설정(Settings) 상세 명세

Hitomi Downloader의 설정 데이터베이스(`hitomi_downloader_GUI.ini` 내 `Preference`, `Downloader` 테이블)를 분석하여 치지직 핵심 기능에 대응시킨 설정 파라미터 규격입니다.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   치지직 다운로더 전역 설정 (Settings)                │
├───────────────────┬────────────────────┬───────────────────────────────┤
│ 1. 라이브 / 자동녹화 │ 2. VOD 다운로드     │ 3. 시스템 / 알림 / 트레이     │
│  - 채널 모니터링   │  - 화질 / 코덱 선택│  - 윈도우 알림 (Toast/Balloon)│
│  - 감시 주기 (분)  │  - 파일명 템플릿   │  - 절전 모드 방지 (Power)     │
│  - 녹화 파일명 서식│  - 쿠키 세션 인증  │  - 트레이 최소화 & 단축키     │
└───────────────────┴────────────────────┴───────────────────────────────┘
```

### 2.1 실시간 라이브 녹화 및 자동 녹화 (Live & Auto-recording)

Hitomi Downloader의 라이브 녹화 핵심은 **"무손실 스트림 복사(-c copy)"**, **"독립 작업 큐 분리"**, **"주기적 채널 모니터링"**입니다.

| 설정 키 (`Key`) | 타입 / 기본값 | 원본 매핑 | 상세 기능 및 동작 규격 |
| :--- | :--- | :--- | :--- |
| `check_live` | `bool` (`True`) | `check_live` | **자동 녹화 마스터 스위치**.<br>활성화 시 등록된 스트리머 목록을 주기적으로 조회하여 방송 시작 시 즉시 녹화 실행. |
| `live_timer` | `int` (`5`) | `live_timer` | **채널 모니터링 폴링 간격 (단위: 분)**.<br>1분 ~ 30분 범위 설정 가능. 백그라운드 타이머(`QTimer`)로 치지직 Live API 상태 조회. |
| `live_format` | `str` | `liveFormat` | **녹화 파일명 서식 템플릿**.<br>기본값: `[{artist}] date:%Y-%m-%d %H：%M; {title}`<br>- `{artist}`: 스트리머 닉네임<br>- `date:...`: 방송 시작 일시 (Windows 금지문자 `:`는 전각 콜론 `：`으로 치환)<br>- `{title}`: 방송 제목 |
| `lives` | `List[LiveChannel]` | `lives` | **등록된 자동 녹화 채널 목록** (JSON 직렬화 저장).<br>개별 채널별로 활성화/일시정지(`pause`), 선호 화질(`quality`), 채널 고유 ID, 썸네일 캐시를 가짐. |
| `live_quality` | `str` (`"best"`) | - | 선호 녹화 품질 (`"best"`, `"1080p"`, `"720p"`). 미제공 시 최상위 가용 화질로 자동 폴백. |
| `live_queue_isolate` | `bool` (`True`) | *Changelog* | **라이브 녹화 작업의 동시 다운로드 슬롯 점유 분리**.<br>VOD의 `max_tasks` 제한과 무관하게 라이브 녹화는 별도의 독립 실행 풀에서 백그라운드 구동. |
| `stream_resilience` | `bool` (`True`) | *Changelog #6722* | **네트워크 일시 단절 및 세그먼트 손상 방어**.<br>HLS 세그먼트 누락 발생 시 녹화를 중단하지 않고 다음 세그먼트로 지속 연결, 완전 단절 시 지정 횟수(기본 3회) 자동 재연결 시도. |
| `duplicate_naming` | `str` (`"timestamp"`) | *Changelog #6895* | **녹화 파일명 분리 보존 정책 (병합 불필요 확정)**.<br>파일명 서식에 실제 녹화 시작 일시(`date:%Y-%m-%d %H：%M`)가 포함되므로, 방송 재시작이나 재연결 시 각 파일은 시작 시각에 의해 자연스럽게 고유 분리 보존됨. 사후 무손실 병합(Concat)은 수행하지 않음. |

#### `LiveChannel` 데이터 모델 구조
```json
{
  "channel_id": "4ebef1eb4194611996dc38abf1d226d1",
  "streamer_name": "마레 플로스",
  "channel_url": "https://chzzk.naver.com/live/4ebef1eb4194611996dc38abf1d226d1",
  "pause": false,
  "preferred_quality": "best",
  "thumbnail_url": "https://...",
  "last_status": "OFFLINE",
  "last_check_time": 1788787307
}
```

---

### 2.2 VOD 다운로드 설정 (VOD Download Settings)

| 설정 키 (`Key`) | 타입 / 기본값 | 원본 매핑 | 상세 기능 및 동작 규격 |
| :--- | :--- | :--- | :--- |
| `vod_quality` | `str` (`"best"`) | `youtubeCombo_res` | **선호 다운로드 화질**.<br>`"best"`, `"1080p60"`, `"1080p"`, `"720p"`, `"480p"`, `"360p"` 중 선택. |
| `codecs_priority` | `List[str]` | `CODECS_PRI` | **비디오 코덱 선호 우선순위**.<br>기본값: `["avc1", "vp9", "av1"]`. (H.264/AVC가 편집기 호환성 및 하드웨어 가속에 가장 안정적이므로 1순위) |
| `vod_format` | `str` | `youtubeFormat` | **VOD 저장 파일명 서식**.<br>기본값: `[{streamer}] date:{%Y-%m-%d}; {title} ({videoNo})`<br>라이브 시작일 미확인 시: `[{streamer}] {title} ({videoNo})` |
| `save_directory` | `str` (`~/Downloads`) | `download directory` | 다운로드 결과 파일 저장 기본 디렉터리 경로. |
| `sync_mtime` | `bool` (`True`) | `youtubeMtimeCheck` | **파일 수정시간(mtime) 동기화**.<br>다운로드 완료된 로컬 파일의 최종 수정시간을 영상 생성일시(업로드일/방송일)로 설정. |
| `cookie_path` | `str` | `cookiejar` | 네이버 로그인 세션 쿠키 저장 경로 (`~/.chzzk_downloader/cookies.txt`).<br>연령제한(성인 인증) 및 비공개/구독자 전용 VOD 다운로드 시 필수 주입. |
| `ffmpeg_args_hls` | `List[str]` | - | **최신 FFmpeg `.m4v` 호환 옵션**.<br>`["-extension_picky", "0", "-allowed_extensions", "ALL"]` 자동 주입으로 fMP4 거부 오류 원천 방지. |

---

### 2.3 시스템, 알림, 트레이 및 전원 설정 (System, Notification & Tray)

| 설정 키 (`Key`) | 타입 / 기본값 | 원본 매핑 | 상세 기능 및 동작 규격 |
| :--- | :--- | :--- | :--- |
| `sound_clipboard` | `bool` (`True`) | `soundClipMon` | 클립보드에서 치지직 URL이 자동 감지되었을 때 효과음 재생. |
| `sound_complete` | `bool` (`True`) | `soundMsg` | VOD 다운로드 완료 또는 라이브 녹화 정상 종료 시 효과음 재생. |
| `notify_tray_message`| `bool` (`True`) | `showTrayMessage` | **윈도우 트레이 풍선/토스트 알림 마스터 스위치**. |
| `notify_on_task_end` | `bool` (`False`) | `showTrayFinished` | 개별 작업(단일 VOD 또는 라이브 녹화) 완료 시 시스템 알림 노출. |
| `notify_on_all_end` | `bool` (`True`) | `showTrayFinishedAll` | 대기 큐의 모든 작업이 다운로드 완료되었을 때 시스템 알림 노출. |
| `notify_on_live_start`| `bool` (`True`) | - | **모니터링 중인 스트리머 방송 시작 시 시스템 알림 노출**.<br>예: `[마레 플로스] 방송이 시작되어 자동 녹화를 시작합니다.` |
| `minimize_to_tray` | `bool` (`False`) | `minimizeToTray` | 메인 창 최소화(`_`) 버튼 클릭 시 작업표시줄 대신 시스템 트레이로 숨김. |
| `close_to_tray` | `bool` (`False`) | `closeToTray` | 메인 창 닫기(`✕`) 버튼 클릭 시 앱을 종료하지 않고 트레이로 최소화. |
| `prevent_sleep` | `bool` (`True`) | `preventSleep` | **Windows 절전 모드 자동 차단**.<br>다운로드 또는 실시간 녹화 진행 중 `SetThreadExecutionState` API를 호출하여 PC가 절전(Sleep) 상태로 진입하는 것을 방지. |
| `auto_start` | `bool` (`False`) | `startup` | Windows 부팅 시 백그라운드(트레이)로 자동 시작. |

---

### 2.4 작업 큐 및 대역폭 제어 (Queue & Bandwidth)

| 설정 키 (`Key`) | 타입 / 기본값 | 원본 매핑 | 상세 기능 및 동작 규격 |
| :--- | :--- | :--- | :--- |
| `max_concurrent_vod`| `int` (`3`) | `dial_task` (기본 9) | **최대 동시 VOD 다운로드 수**.<br>초과 등록된 작업은 `QUEUED` 상태로 대기하다가 선행 작업 완료 시 자동 시작. |
| `speed_limit_enabled`| `bool` (`False`) | `speedCheck` | 전체 다운로드 속도 제한 활성화 여부. |
| `speed_limit_rate` | `int` (`0`) | `speedBox` / `limitBox` | 최대 허용 대역폭 (단위: KB/s 또는 MB/s). |
| `delete_to_trash` | `bool` (`True`) | `trash` | 파일 삭제 시 영구 삭제 대신 Windows 휴지통(Recycle Bin)으로 안전하게 이동. |
| `confirm_deletion` | `bool` (`True`) | `delete without warning` | 작업 및 로컬 파일 삭제 시 사용자 확인 모달 팝업 표시 여부. |

---

## 3. 전반적인 UI/UX 디자인 및 레이아웃 사양

Hitomi Downloader의 컴팩트한 메인 프레임과 정보 집약적인 작업 카드를 계승하고, 치지직 다운로더의 디자인 시스템(Dark Surface, 네온 그린 포인트)에 맞게 정제한 UI 구조입니다.

### 3.1 메인 윈도우 전체 구조도

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Chzzk Downloader]                       [📌 항상위] [⚙️ 설정] [➖] [⛶] [✕] │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌───┐ ┌───────────────────────────────────────────────────────┬───┐ ┌──────┐ │
│ │📋 │ │ 치지직 VOD 또는 라이브 채널 URL을 입력하세요...       │ ✕ │ │다운로드│
│ └───┘ └───────────────────────────────────────────────────────┴───┘ └──────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│  [작업 목록 (Task List)]                           총 2개 작업 (1개 실행 중) │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ ┌──────────┐ [LIVE] [마레 플로스] 2026-09-09 심야 잡담 방송               │ │
│ │ │ 썸네일   │                                 [📁] [▶] [⏹] [🗑️] [🗨️!]   │ │
│ │ │ 120x68   │ 🔴 녹화 중 | 01:24:12 | 1.84 GB | 4.5 MB/s                  │ │
│ │ └──────────┘ [Z] [1080p60]                                               │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ ┌──────────┐ [VOD] [양아지] 유튜브 기괴 영상 살펴보기                    │ │
│ │ │ 썸네일   │                                 [📁] [▶] [⏹] [🗑️] [🗨️!]   │ │
│ │ │ 120x68   │ [██████████████░░░░░░░░░░░░] 54% | 12.4 MB/s | ETA 03:20    │ │
│ │ └──────────┘ [Z] [1080p]                                                 │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│  🟢 자동 녹화 감시 중 (2개 채널) | 총 속도: 16.9 MB/s | 남은 용량: 142.5 GB  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

### 3.2 작업 카드(Task Card) 4분면 구조 상세

작업 카드는 **120×68px 16:9 썸네일** 영역과 시계 방향 4분면 구역으로 엄격히 분할됩니다.

```
┌──────────────┬──────────────────────────────────────────┬────────────────┐
│              │ (1번 위치) 작업 제목 및 스트리머 정보      │ (2번 위치)     │
│              │  - [상태뱃지] [스트리머] 방송/영상 제목    │  호버 액션툴바 │
│  썸네일 영역 │  - 긴 제목 좌측 정렬 자동 줄바꿈          │  [📁][▶][⏹][🗑️]│
│  (120 x 68)  ├──────────────────────────────────────────┴────────────────┤
│              │ (3번 위치) 진행 상태 표시 영역                            │
│  - LIVE 뱃지 │  - VOD: 프로그레스바, 진행률(%), 속도(MB/s), ETA          │
│  - 재생 시간 │  - LIVE: 🔴 REC, 경과 시간, 누적 용량(GB), 수신 비트레이트│
│              ├──────────────────────────────────────────┬────────────────┤
│              │ (4번 위치) 플랫폼 뱃지 & 에러/인증 액션   │                │
│              │  - [Z] 치지직 바로가기                   │                │
│              │  - [🗨️!] 작업 상세/진단, [🍪]쿠키, [N]로그인│                │
└──────────────┴──────────────────────────────────────────┴────────────────┘
```

#### 구역별 인터랙션 규칙
1. **1번 위치 (좌상단)**:
   - 텍스트: `[{스트리머}] {제목}` 또는 `[{스트리머}] {%Y-%m-%d} {title}`.
   - 오류 발생 시: `Invalid: {url}` 또는 `Login required; Please login\n{url}` (빨간색 강조).
2. **2번 위치 (우상단)**:
   - **Row Hover 시에만 노출**되는 회색조 아이콘 그룹.
   - 구성: `폴더 열기(📁)`, `재생(▶)`, `중지(⏹)`, `삭제(🗑️)`, `진단 정보(🗨️!)`.
   - 각 아이콘 마우스 진입 시 툴팁 및 다크 하이라이트 박스 제공.
3. **3번 위치 (우하단)**:
   - 실시간 다운로드/녹화 수치 표시. 오류 상태(`FAILED_*`)에서는 시각적 노이즈를 줄이기 위해 완전 숨김(`hide()`).
4. **4번 위치 (좌하단)**:
   - 치지직 네온 그린 뱃지 (`[Z]`, 클릭 시 원본 방송 링크 이동 확인 모달).
   - 성인/로그인 필요 시 쿠키 설정(`🍪`) 및 네이버 로그인(`N`) 원클릭 바로가기 버튼 노출.
5. **좌측 세로 상태 바 (Visual Status Bar)**:
   - 정상/대기: 없음 (기본 테두리)
   - 치명적 오류 / 로그인 필요: **5px 빨간 바 (`#ef4444`)** + 은은한 레드 틴트
   - 다운로드 중단 / 네트워크 오류: **5px 주황 바 (`#f59e0b`)** + 은은한 오렌지 틴트
   - 실시간 녹화 중: **5px 네온 그린 바 (`#00ffa3`)** + REC 펄스 애니메이션

---

### 3.3 작업 상세 정보 / 에러 진단 창 (`TaskInfoWindow`)

Hitomi Downloader에서 단축키 <kbd>A</kbd>를 누르면 나타나는 작업 상세 정보 창을 벤치마킹한 모듈입니다.

- **성격**: 메인 창을 차단하지 않는 비모달(Modeless) 팝업 창.
- **주요 표시 데이터**:
  - 고유 작업 ID (`uid`) 및 원본 요청 URL
  - 추출된 포맷 정보 (해상도, 비디오 코덱, 오디오 코덱, 프레임레이트)
  - 실제 호출된 백엔드 인자 (yt-dlp 파라미터 또는 FFmpeg 파이프라인 명령어)
  - 네트워크 응답 헤더 및 오류 발생 시 파이썬 전체 Traceback 원문
- **편의 기능**:
  - 하단 **`[클립보드에 복사]`** 버튼 제공 (GitHub 이슈 리포트 및 오류 디버깅 시 즉각 활용 가능).

---

### 3.4 시스템 트레이(System Tray) 및 백그라운드 상호작용

- **트레이 아이콘 상태 표시**:
  - 기본 상태: 앱 기본 로고.
  - 활성 다운로드/녹화 중: 작업 수 뱃지 또는 회전 인디케이터 오버레이.
- **마우스 호버 툴팁**:
  - `Chzzk Downloader - 실행 중인 작업 2개 (14.2 MB/s) | 감시 채널: 3개`
- **트레이 우클릭 컨텍스트 메뉴**:
  - `창 열기 (Show Window)` (기본 더블클릭 동작)
  - `모든 작업 일시정지 (Pause All)` / `모든 작업 재개 (Resume All)`
  - `―` (구분선)
  - `클립보드 자동 감지 활성화 (체크박스 토글)`
  - `자동 녹화 지금 확인 (Check Lives Now)`
  - `―` (구분선)
  - `환경설정 (Preferences...)`
  - `종료 (Exit)`

---

## 4. 단축키(Shortcuts) 체계 명세

Hitomi Downloader의 표준 키 매핑을 기반으로 치지직 특화 단축키 체계를 정의합니다.

| 단축키 (`Shortcut`) | 기능 설명 | 세부 동작 |
| :--- | :--- | :--- |
| <kbd>Enter</kbd> | 다운로드 / 시작 | URL 입력창에서는 다운로드 시작, 목록에서는 선택된 작업 시작 |
| <kbd>Ctrl</kbd> + <kbd>Enter</kbd> | 저장 폴더 열기 | 선택된 작업의 다운로드/녹화 대상 폴더를 윈도우 탐색기로 오픈 |
| <kbd>Space</kbd> | 일시정지 / 재개 | 선택된 작업 일시정지 또는 이어받기 |
| <kbd>F5</kbd> | 환경설정 창 열기 | Modeless 설정 창(`SettingsWindow`) 호출 |
| <kbd>Ctrl</kbd> + <kbd>P</kbd> | 항상 위에 고정 (Pin) | 메인 창 Always-on-top 속성 토글 |
| <kbd>Ctrl</kbd> + <kbd>H</kbd> | 트레이로 최소화 | 메인 창을 시스템 트레이로 즉시 숨김 |
| <kbd>Ctrl</kbd> + <kbd>Q</kbd> | 패닉 락 (Quick Hide) | 화면에서 즉시 창을 감추고 트레이 아이콘도 최소화 상태로 전환 |
| <kbd>A</kbd> | 작업 상세 정보 (Info) | 선택된 작업의 `TaskInfoWindow` 진단 팝업 오픈 |
| <kbd>Delete</kbd> | 목록에서 제거 | 선택된 작업을 작업 목록에서만 제거 (로컬 파일 유지) |
| <kbd>Shift</kbd> + <kbd>Delete</kbd> | 파일 완전 삭제 | 확인 모달(M01) 후 다운로드된 로컬 파일을 휴지통으로 이동 및 목록 삭제 |
| <kbd>Shift</kbd> + <kbd>Enter</kbd> | 브라우저에서 열기 | 선택된 VOD 또는 라이브 방송 페이지를 기본 웹 브라우저로 오픈 |

---

## 5. 경량화 및 치지직 플랫폼 특화 최적화 규칙

Hitomi Downloader와 비교하여 본 치지직 다운로더가 구현해야 할 차별화 및 경량화 핵심 규칙입니다.

1. **무거운 레거시 모듈 완전 제거**:
   - 수백 개 사이트 스크래퍼, 정적 이미지 분할 다운로더, ZIP 압축/변환기, 자체 DPI 패킷 우회 엔진 등 본 프로젝트와 무관한 코드를 완전히 배제하여 150MB+ exe를 가벼운 단일 앱으로 최적화.
2. **치지직 전용 HLS fMP4 세그먼트 보호**:
   - 최신 FFmpeg(v6.1+)의 `.m4v` 거부 문제를 방지하기 위해 `-extension_picky 0 -allowed_extensions ALL` 인자를 전역 주입.
   - 네이버 LiveCloud CDN 차단(400 Bad Request) 방지를 위한 `Referer: https://chzzk.naver.com/` 헤더 기본 적용.
3. **네이버 로그인 세션 영속성**:
   - 성인/연령제한 VOD 및 채널 멤버십 라이브 녹화를 위해 `NID_AUT`, `NID_SES` 쿠키를 안전하게 관리하고 세션 만료 시 액션 토스트(T06)로 즉각적인 갱신 유도.
4. **라이브 모니터링 폴링 최적화**:
   - 불필요한 무거운 HTML 파싱을 지양하고, 가벼운 치지직 라이브 상태 JSON API (`GET /service/v2/channels/{channelId}/live-detail`)만을 비동기 단발 호출하여 리소스 및 네트워크 트래픽 절약.

---

## 6. AI Agent 구현 체크리스트 및 데이터 모델 규격

Agent가 코드를 작성할 때 즉시 임포트하여 사용할 수 있는 데이터 모델 및 상태 Enum 정의입니다.

```python
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional

class TaskType(Enum):
    VOD = auto()
    LIVE = auto()

class TaskStatus(Enum):
    QUEUED = auto()
    ANALYZING = auto()
    READY = auto()
    DOWNLOADING = auto()
    RECORDING = auto()       # 실시간 라이브 녹화 중
    STOPPED = auto()
    COMPLETED = auto()
    FAILED_INVALID = auto()
    FAILED_LOGIN_REQUIRED = auto()
    FAILED_DOWNLOAD = auto()

@dataclass
class TaskProgress:
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed_bytes_per_sec: float = 0.0
    elapsed_seconds: float = 0.0
    eta_seconds: Optional[float] = None
    percent: float = 0.0

@dataclass
class LiveStreamerEntry:
    channel_id: str
    streamer_name: str
    channel_url: str
    is_paused: bool = False
    preferred_quality: str = "best"
    thumbnail_data: Optional[bytes] = None
    last_status: str = "OFFLINE"
    last_check_timestamp: float = 0.0
```

---

## 7. 연계 문서 및 가이드라인
- **백엔드 아키텍처 상세**: [DOWNLOADER_GUI_ARCHITECTURE.md](file:///c:/Users/%EC%9D%B4%ED%99%8D%EC%9B%90/Desktop/chzzk_downloader/docs/DOWNLOADER_GUI_ARCHITECTURE.md)
- **UI 피드백 및 모달/토스트 카탈로그**: [UI_FEEDBACK_CATALOG.md](file:///c:/Users/%EC%9D%B4%ED%99%8D%EC%9B%90/Desktop/chzzk_downloader/docs/UI_FEEDBACK_CATALOG.md)
- **티켓 및 작업 관리**: [GitHub Issues (Yumetri/chzzk_downloader/issues)](https://github.com/Yumetri/chzzk_downloader/issues)

