# NoticeStore

센트리피전

[프로젝트 문서](./docs/README.md)

## 후보 선택 LLM 설정

애매한 공지 API 후보를 고르는 단계는 OpenAI와 Gemini를 모두 지원한다.
추출·정규화 단계는 기존처럼 결정론적으로 동작하며 LLM을 사용하지 않는다.

```env
LLM_PROVIDER=openai # openai 또는 gemini

OPEN_AI_API_KEY_SELECT_API=...
OPENAI_MODEL=gpt-4.1-mini

GEMINI_API_KEY_SELECT_API=...
GEMINI_MODEL=gemini-3.5-flash-lite
```

설정 변경 후 컨테이너를 재시작해야 한다.

```bash
docker compose up -d --build api crawler_worker
```

두 공급자의 키·모델·구조화 출력 경로를 실제 API로 한 번에 점검한다.

```bash
docker compose exec api python scripts/test_llm_providers.py
docker compose exec api python scripts/test_llm_providers.py --provider gemini
```

이 스모크 테스트는 실제 토큰을 소량 사용하며 API 키 값은 출력하지 않는다.
