---
name: pr-review-check
description: Use when the user asks to check open pull requests, inspect review comments or feedback from maintainers, and identify PRs that need attention.
---

# PR Review Check (오픈 PR 리뷰 코멘트 검사 매뉴얼)

이 스킬은 현재 GitHub 저장소에 열려 있는(Open) 모든 Pull Request의 리뷰 및 코멘트 상태를 일괄 조회하여, 메인테이너나 리뷰어의 피드백이 달린 PR을 즉시 탐지하고 대응할 수 있도록 돕는 자동화 워크플로우입니다.

## 1. 실행 목적 및 사용 시점

- **사용 시점**:
  - "열려 있는 PR 중 코멘트 달린 거 확인해줘"
  - "PR 리뷰 현황 점검해줘"
  - 새 작업을 시작하기 전 처리해야 할 기존 PR 피드백이 있는지 확인할 때
- **주요 기능**:
  - `gh CLI`를 통해 대상 저장소의 Open PR 목록 조회
  - 각 PR별 리뷰(Reviews) 및 이슈 코멘트(Comments) 전수 파싱
  - 최신 피드백 작성자, 등록 시점, 본문 요약 표시
  - 대응이 필요한 관련 브랜치 이름과 PR 링크 제공

## 2. 에이전트 실행 절차

사용자가 PR 리뷰 검사를 요청하면 아래 스크립트를 실행합니다:

```bash
# 기본 upstream 저장소(Yumetri/chzzk_downloader) PR 검사
python .agents/skills/pr-review-check/scripts/check_prs.py

# 특정 저장소 지정 검사 시
python .agents/skills/pr-review-check/scripts/check_prs.py <owner/repo>
```

## 3. 피드백 발견 시 후속 대응 가이드 (AGENTS.md 준수)

코멘트 또는 리뷰가 발견된 경우 `AGENTS.md`의 **5.1 사용자 질의·코멘트 우선 응답 및 진행 방안 사전 승인 원칙**에 따라 아래 순서로 대응합니다:

1. **내용 분석 및 브랜치 파악**:
   - 피드백 내용을 정밀 분석하고 해당 PR의 `headRefName` 브랜치를 확인합니다.
2. **사용자 공유 및 승인 획득**:
   - 피드백 내용, 기술적 검토 결과, 문서/코드 변경 계획을 사용자에게 먼저 설명하고 승인을 받습니다.
3. **브랜치 체크아웃 및 수정**:
   - `git checkout <branch>` 이동 후 TDD 및 코딩 컨벤션에 맞춰 수정합니다.
4. **품질 검증**:
   - `quick-verify` 스킬을 통해 린트, 타입, 테스트 통과를 확인합니다.
5. **커밋, 푸시 및 답변 코멘트 등록**:
   - 원격 브랜치에 푸시 후 `gh pr comment <number> --body "..."`로 상세한 답변을 남깁니다.
