# 공지저장소 (NoticeStore)

## 선택·추출 에이전트 LLM 설정

애매한 공지 API 후보 선택, 결정론적 규칙으로 처리할 수 없는 구조의 규칙
추출, 신규 규칙 결과의 최초 승인은 OpenAI와 Gemini를 모두 지원한다. 승인된
규칙의 정상 반복 크롤링은 LLM 호출 없이 결정론적으로 동작한다.
세부 요구사항은 로컬 운영 문서를 참고한다.

```env
LLM_PROVIDER=openai # openai 또는 gemini

OPEN_AI_API_KEY_SELECT_API=...
OPEN_AI_API_KEY_VIEW_SELECTOR=...
OPEN_AI_API_KEY_RULE_EXTRACTOR=...
OPEN_AI_API_KEY_RESULT_EVALUATOR=...
OPENAI_MODEL=gpt-4.1-mini
# 선택 사항: OPENAI_VIEW_SELECTOR_MODEL, OPENAI_RULE_EXTRACTOR_MODEL,
# OPENAI_RESULT_EVALUATOR_MODEL

GEMINI_API_KEY_SELECT_API=...
GEMINI_API_KEY_VIEW_SELECTOR=...
GEMINI_API_KEY_RULE_EXTRACTOR=...
GEMINI_API_KEY_RESULT_EVALUATOR=...
GEMINI_MODEL=gemini-3.5-flash-lite
# 선택 사항: GEMINI_VIEW_SELECTOR_MODEL, GEMINI_RULE_EXTRACTOR_MODEL,
# GEMINI_RESULT_EVALUATOR_MODEL

# migration 적용 및 shadow 검증 후 활성화
EXTRACTION_AGENT_ENABLED=false
EXTRACTION_AGENT_ROLLOUT_MODE=new_sites # new_sites 또는 all
```

단계별 키를 생략하면 기존 Selector 키를 재사용한다. 기능 활성화 전
[`20260825_add_extraction_agent_telemetry.sql`](./migrations/20260825_add_extraction_agent_telemetry.sql)을
적용해야 한다. 설정 변경 후 컨테이너를 재시작한다.

단계적 활성화와 중단 기준은 로컬 운영 문서를 따른다.

```bash
docker compose up -d --build api crawler_worker
```

두 공급자의 키·모델·구조화 출력 경로를 실제 API로 한 번에 점검한다.

```bash
docker compose exec api python scripts/test_llm_providers.py
docker compose exec api python scripts/test_llm_providers.py --provider gemini
```

이 스모크 테스트는 실제 토큰을 소량 사용하며 API 키 값은 출력하지 않는다.

## 크롤러 응답 크기 제한

외부 URL 응답은 압축 전송 크기와 압축 해제 크기를 각각 제한한다.
두 값의 기본값은 5 MiB(`5242880` bytes)이며, `0` 또는 64 MiB를
초과하는 값은 무제한 설정으로 사용하지 않고 안전한 기본값으로 되돌린다.

```env
CRAWLER_MAX_TRANSFER_BYTES=5242880
CRAWLER_MAX_DECODED_BYTES=5242880
```

설정은 후보 수집, 후보 재현 검증, 실제 공지 수집에 공통 적용된다.
변경 후에는 `crawler_worker`를 재시작해야 한다.
