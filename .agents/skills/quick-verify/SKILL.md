---
name: quick-verify
description: Use when the user asks to quickly run all code quality checks (Ruff lint, Ruff format, Pyrefly type check, Pytest) for the chzzk_downloader project.
---

# Quick Verify (단축 품질 검증 매뉴얼)

이 스킬은 프로젝트의 4단계 품질 검사(린트, 포맷, 타입, 테스트)를 오타나 누락 없이 한 번에 순차 실행하고 요약하는 자동화 워크플로우입니다.

## 1. 실행 파이프라인 개요

- **1단계 (Ruff Linter)**: `uv run --no-sync ruff check .`
- **2단계 (Ruff Formatter)**: `uv run --no-sync ruff format --check .`
- **3단계 (Pyrefly Type Check)**: `uv run --no-sync pyrefly check`
- **4단계 (Rules Ratchet Check)**: `uv run --no-sync python tools/check_rules.py`
- **5단계 (Pytest Test Suite)**:
  - 기본 (전체 검증): `uv run --no-sync pytest` (310+ 테스트 전체)
  - 고속 모드 (`--fast`): `uv run --no-sync pytest tests/test_ui_feedback_catalog.py` (핵심 카탈로그 스모크 테스트)

## 2. 에이전트 실행 절차

사용자가 빠른 품질 검사를 요청하면 아래 스크립트를 실행합니다:

```bash
# 전체 테스트 실행 (권장)
uv run --no-sync python .agents/skills/quick-verify/scripts/verify.py

# 또는 고속 스모크 테스트 실행
uv run --no-sync python .agents/skills/quick-verify/scripts/verify.py --fast
```

## 3. 실패 시 자동 복구 가이드

- **Ruff 린트/포맷 실패**:
  - 포맷 자동 적용: `uv run --no-sync ruff format .`
  - 린트 자동 수정: `uv run --no-sync ruff check . --fix`
- **Pyrefly 타입 에러**:
  - 타입 불일치 및 미정의 속성 위치 확인 후 수정.
- **Pytest 실패**:
  - 실패한 테스트 함수 및 역추적(Traceback) 상세 분석 후 TDD 원칙에 따라 코드 결함 수정.
