---
name: workflow-gate
description: Use when verifying the 7-phase collaboration lifecycle (P1~P7) and running machine guards (check_workflow.py) before shipping or concluding a session.
---

# Workflow Gate (협업 라이프사이클 기계 검증 스킬)

이 스킬은 `AGENTS.md` §9 및 `docs/AGENT_WORKFLOW.md`에 정의된 **7단계 협업 라이프사이클(P1~P7)**이 단계를 건너뛰지 않고 정상 완결되었는지 기계적으로 판정하고 검증하는 자동화 도구입니다.

## 1. 7단계 라이프사이클 상태 머신

1. **P1 [Plan & Briefing]**: 사용자 요구 분석 ➔ TDD/작업 계획 브리핑 ➔ 사용자 사전 승인
2. **P2 [TDD Red]**: 프로덕션 수정 전 실패하는 테스트 작성 ➔ `pytest` 실패(Red) 실행 로그 확인
3. **P3 [TDD Green]**: 최소 프로덕션 코드 구현 ➔ 해당 테스트 통과(Green)
4. **P4 [Adversarial Audit]**: 에이전트 자발적 서브에이전트 가동 ➔ 엣지 케이스 감사 ➔ 경계값 TDD 보강
5. **P5 [4대 기계 검증]**: Ruff, Pyrefly, check_rules.py, Pytest 전수 검증
6. **P6 [Handoff & Report]**: 아키텍처 변경 시 `reports/*.html` 생성 ➔ 6대 Handoff 양식 출력
7. **P7 [Ship]**: 사용자 최종 승인 ➔ Git 커밋, 데스크톱 동기화(`desktop-sync`), 푸시/PR

## 2. 에이전트 실행 절차

세션 종료 전이나 커밋(Ship) 직전, 아래 명령으로 워크플로우 가드를 전수 검증합니다:

```bash
# 전체 기계 가드 검증 (P5 4대 검증 + P6 오늘자 HTML 보고서 필수 확인)
uv run --offline python tools/check_workflow.py --require-report

# 고속 점검 모드 (린트/타입/규칙 + 보고서 존재 확인)
uv run --offline python tools/check_workflow.py --quick --require-report
```

## 3. 검증 결과 판정 및 후속 조치

- **[SUCCESS]**: 모든 P1~P6 필수 산출물과 기계 완료 조건을 통과했으므로 즉시 세션 인계 정보(6대 표준 양식)를 출력하고 사용자에게 P7(Ship) 승인을 요청합니다.
- **[FAILURE - Phase 5 누락]**:
  - Ruff 포맷/린트 실패 시 `uv run --offline ruff format .` 또는 `ruff check . --fix` 수행.
  - 규칙 래칫 실패 시 `tools/check_rules.py` 검사 규칙(R/T/M) 준수 여부 재확인.
  - Pytest 실패 시 TDD 원칙에 따라 코드 결함 수정.
- **[FAILURE - Phase 6 누락]**:
  - `src/` 코드 변경이 존재하는데 오늘자 HTML 분석 보고서가 없는 경우, 즉시 `explain-diff-html` 스킬을 호출하여 `reports/YYYY-MM-DD-explanation-<slug>.html`을 생성합니다.
