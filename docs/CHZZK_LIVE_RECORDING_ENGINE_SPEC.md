# 치지직 실시간 라이브 녹화 엔진 및 fMP4 무결성 검증 규격서
> **관련 이슈**: `#95 [RFC/설계 논의] 실시간 라이브 녹화 엔진 구성 전략`  
> **참조 문서**: `docs/DOWNLOADER_GUI_ARCHITECTURE.md`, `docs/HITOMI_CHZZK_FEATURE_DESIGN_SPEC.md`

---

## 1. 개요 및 엔진 채택 전략

본 문서는 치지직(CHZZK) 실시간 라이브 스트리밍 방송의 무손실 녹화, 개별 작업 단위의 타임머신(DVR) 제어, 그리고 fMP4(fragmented MP4) 특성을 활용한 사후 무결성 검증 시스템의 아키텍처 및 상세 기술 규격을 정의합니다.

### 1.1 벤치마크 및 엔진 선정 배경
치지직 라이브 스트림은 fMP4 기반의 LLHLS(Low-Latency HLS) 매니페스트를 통해 제공됩니다. 본 프로젝트는 기존 도구들의 장단점을 정밀 분석하여 최적의 방안을 채택했습니다.

| 구분 | Hitomi Downloader 모델 | recordWEB v1.2.9 모델 | **치지직 다운로더 확정 사양 (#95)** |
| :--- | :--- | :--- | :--- |
| **녹화 파이프라인** | FFmpeg 단독 (`-c copy`) | Streamlink 인제스트 + FFmpeg Muxing | **Streamlink 인제스트 기반 fMP4 무손실 직접 저장** |
| **타임머신 (DVR)** | ❌ 지원 불가 | ✅ 전역 설정으로 지원 (개별 제어 불가) | ✅ **개별 작업/채널 단위 독립 제어** |
| **세그먼트 복원력** | FFmpeg reconnect (소켓 프리징 취약) | 세그먼트당 최대 12회 재시도 | **Streamlink 세그먼트 재시도 방어** (상세 설명 참조) |
| **컨테이너 보존** | MP4 (단일 moov) | 확장자와 무관하게 fMP4 무손실 직접 저장 | **무손실 fMP4 원본 그대로 안전 보존** |
| **사후 무결성 검증** | 단순 파일 크기/FFprobe duration | 미지원 | **fMP4 `moof` 박스 기반 초고속 누락 정밀 진단** |

> **💡 Streamlink 세그먼트 재시도 방어 메커니즘**:  
> 실시간 HLS 스트리밍 수신 중 네트워크 순간 단절, CDN 병목/스로틀링, 일시적 HTTP 404/502 응답이 발생했을 때:
> - FFmpeg는 소켓 프리징(무한 대기)에 빠지거나 프로세스가 예기치 않게 종료되는 반면,
> - Streamlink는 `--hls-segment-attempts <N>`(기본 3~5회 재시도), `--hls-segment-timeout`(조각별 타임아웃) 및 내부 슬라이딩 버퍼 큐를 통해 일시적인 네트워크 장애 상황에서도 세그먼트 누락 없이 끈질기게 재시도하여 녹화 파이프라인의 생존성을 극대화합니다.

---

## 2. 개별 작업 단위 타임머신(DVR) 제어 체계

기존 `recordGUI` 등 전문 녹화 툴은 타임머신 기능이 **전역(Global) 설정**으로만 통제되어, 사용자가 특정 채널만 방송 처음부터 받고 다른 채널은 현재 시점부터 받는 등의 세분화된 운용이 불가능했습니다.

본 프로젝트에서는 **URL 입력 바, 작업 카드 및 채널 단위(Per-Input/Per-Task/Per-Channel Configuration)**로 타임머신을 완벽히 독립 제어합니다.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   타임머신(DVR) 계층형 제어 아키텍처                  │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 메인 URL 입력 바 토글 (MainWindow Top Bar)                          │
│    - 실시간 방송 링크 직접 입력 시 즉석에서 [타임머신 ON/OFF] 스위치 제공│
│                                                                        │
│ 2. 채널별 기본 설정 (LiveChannel.use_dvr: bool)                        │
│    - 자동 감시 채널 등록 시 채널별 선호 타임머신 기본값 지정          │
│                                                                        │
│ 3. 실시간 작업 카드 개별 토글 (LiveTaskCard Widget)                    │
│    - 큐에 등록된 개별 녹화 카드에서 즉석으로 [타임머신 ON/OFF] 토글    │
│                                                                        │
│ 4. Streamlink 실행 파라미터 동적 분기                                  │
│    - use_dvr == True  ➔ streamlink ... --hls-live-restart            │
│    - use_dvr == False ➔ streamlink ... (현재 실시간 라이브 엣지 수신) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. fMP4 구조적 특성과 사후 세그먼트 무결성 검증

### 3.1 일반 MP4 vs fMP4의 근본적 차이

* **일반(비-프래그먼트) MP4**:
  * 전체 파일의 모든 샘플 메타데이터(위치, 크기, 길이, 키프레임)가 파일 앞단이나 뒷단의 단일 `moov` 박스(`stbl` 내의 `stts`, `stsz`, `stsc`, `stco`)에 집중되어 있습니다.
  * 스트리밍 중 비정상 중단되면 `moov`가 기록되지 않아 파일 전체가 재생 불가능해질 위험이 있습니다.
* **fMP4 (fragmented MP4)**:
  * 앞단의 `moov`는 트랙 정의만 최소한으로 담고, 실제 영상/음성 데이터는 파일 전체에 걸쳐 **수많은 `moof`(Movie Fragment) + `mdat`(Media Data) 쌍**으로 분산 저장됩니다.
  * 각 `moof` 조각이 **자기 자신의 메타데이터(재생 시간, 샘플 크기, 시퀀스 번호)를 스스로 들고 있으므로**, 녹화가 도중에 강제 종료되어도 이전까지 누적된 프래그먼트는 100% 정상 재생됩니다.
  * **핵심 이점**: 각 조각이 독립된 메타데이터를 지니므로, 역설적으로 **"파일 내에 세그먼트 손실이나 타임라인 누락이 발생했는가?"**를 사후에 완벽히 진단할 수 있습니다.

```
[ 일반 MP4 ]
┌──────┬───────────────────────────────────────────┬──────────────┐
│ ftyp │ mdat (전체 미디어 스트림)                  │ moov (전체)  │
└──────┴───────────────────────────────────────────┴──────────────┘

[ fMP4 (치지직 LLHLS 규격) ]
┌──────┬──────┬─────────┬─────────┬─────────┬─────────┬───────┐
│ ftyp │ moov │ moof(1) │ mdat(1) │ moof(2) │ mdat(2) │  ...  │
└──────┴──────┴─────────┴─────────┴─────────┴─────────┴───────┘
                  │                   │
                  ├─ mfhd (seq=1)     ├─ mfhd (seq=2)
                  ├─ tfdt (time=0)    ├─ tfdt (time=2000)
                  └─ trun (samples)   └─ trun (samples)
```

---

### 3.2 사후 세그먼트 손실/간극(Gap) 진단 알고리즘

`fMP4 Integrity Checker`는 FFmpeg나 무거운 미디어 디코더를 일절 호출하지 않고, **순수 바이너리 레벨에서 MP4 Box Header를 순차 탐색**합니다 (수 GB 파일도 수십 ms 이내 분석 완료).

#### 1) 시퀀스 번호 연속성 검사 (`mfhd`)
- 각 `moof` 박스 내부의 `mfhd` (Movie Fragment Header Box)에는 `sequence_number`가 기록됩니다.
- **검사 규칙**:
  $$\text{Expected } Seq_{i} = Seq_{i-1} + 1$$
  - $Seq_{i} > Seq_{i-1} + 1$ 이면 중간 세그먼트가 유실(Drop)된 것으로 확정합니다.
- **⚠ 실전 보정 필수**:
  - 일부 인코더는 여러 개의 물리적 `moof`가 같은 `sequence_number`를 공유합니다 (예: 비디오/오디오 트랙별로 `moof`가 분리된 구조).
  - 이를 그대로 검사하면 정상 파일에서도 대량의 오탐(False Positive)이 발생합니다.
  - **보정 알고리즘**: `moof`를 순서대로 훑으며 **연속으로 동일한 `seq`가 나오는 구간을 하나의 그룹으로 묶은 뒤, 그 그룹 단위로 위 연속성 규칙을 적용**합니다.

#### 2) 미디어 타임스탬프 불연속(Gap) 검사 (`tfdt` & `trun`)
- **트랙별(`traf`)로 독립 검사 수행**. 각 조각의:
  - `tfdt.base_media_decode_time`: 시작 시각 (권위 있는 절대값)
  - `trun`의 `sample_duration` 총합: 해당 조각의 실제 길이
- **검사 규칙**:
  $$\Delta t = tfdt_{next} - \left( tfdt_{curr} + \sum \text{sample\_duration} \right)$$
  - $|\Delta t| > \text{허용 임계치(기본 2ms)}$ 이면 **유실($\Delta t > 0$) 또는 중첩($\Delta t < 0$)**으로 기록합니다.
- **트랙 독립 검사의 필요성**:
  - 한쪽 트랙(예: 오디오)만 부분 유실된 경우 다른 트랙의 `seq`는 정상일 수 있으므로, 1번(시퀀스 검사)만으로는 검출하지 못하는 트랙별 누락을 2번 검사로 완벽히 포착합니다.

#### 3) 진단 결과 데이터 모델
```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SegmentGap:
    track_id: int  # 어느 트랙에서 발생했는지 (2번 검사는 트랙별이므로 필수)
    gap_type: str  # "sequence_gap" | "timestamp_gap" | "timestamp_overlap"
    start_time_sec: float
    end_time_sec: float
    lost_duration_sec: float
    expected_seq: int | None = None
    actual_seq: int | None = None


@dataclass
class Fmp4IntegrityReport:
    file_path: Path
    total_fragments: int
    total_duration_sec: float
    is_healthy: bool
    missing_fragment_count: int
    gaps: list[SegmentGap] = field(default_factory=list)
```

---

## 4. 컨테이너 저장 정책

- **무손실 fMP4 원본 직접 보존**:
  - 녹화가 완료된 파일은 별도의 FFmpeg 변환(단일 moov 일반 MP4로의 Muxing) 과정을 거치지 않고, 수신된 fMP4 원본 컨테이너 그대로 저장합니다.
  - **이유**: 사후 변환은 CPU 점유율과 디스크 I/O를 추가로 소모하며, 대용량 파일(수십 GB) 처리 시 사용자 대기 시간을 유발하고 예기치 못한 인코딩 결함을 초래할 수 있습니다. 최신 미디어 플레이어(팟플레이어, VLC, 브라우저)는 fMP4를 네이티브로 완벽히 지원합니다.

---

## 5. 서브프로세스 생명주기 및 Windows 안전 제어

1. **프로세스 격리 및 워치독**:
   - Streamlink 프로세스는 UI 스레드를 일절 블로킹하지 않도록 `QProcess` 또는 `subprocess.Popen` 기반의 독립 백그라운드 워커에서 구동합니다.
2. **Windows 안전 종료 (Graceful Termination)**:
   - 사용자가 녹화 중지(`STOP`)를 누르거나 프로그램 종료 시, `taskkill /F`와 같은 강제 프로세스 사살을 금지합니다.
   - 표준 입력 닫기 또는 `SIGINT`(Windows의 경우 `CTRL_BREAK_EVENT` 또는 안전 종료 시그널)를 전송하여, Streamlink가 마지막으로 수신 중이던 `moof`+`mdat` 조각을 파일에 안전하게 플러시한 뒤 정상 종료되도록 보장합니다.
3. **네트워크 장애 방어 파라미터**:
   - `--hls-segment-attempts 5`: 세그먼트 다운로드 실패 시 끈질기게 재시도.
   - `--hls-segment-timeout 10.0`: CDN 정체 시 행(Hang) 방지.
   - `--http-header "User-Agent=..."` 및 `--http-header "Referer=https://chzzk.naver.com/"` 필수 주입.
