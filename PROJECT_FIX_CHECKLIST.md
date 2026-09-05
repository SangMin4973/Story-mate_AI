# Story-mate AI 문제점 개선 체크리스트

## 우선순위 높음

- [x] `chatbot_sql.py`와 `quiz.py`의 Chroma DB 경로 규칙을 통일하기
  - 채팅은 `book_title/character_name/data/embedding`을 사용합니다.
  - 서술형 퀴즈 평가는 `book_title/data/embedding`을 사용합니다.
  - 작품별 실제 폴더 구조가 섞여 있어 일부 캐릭터에서 DB를 못 찾을 가능성이 큽니다.

- [x] `book_title`, `character_name`, `quiz_type`, `query` 필수값 검증 추가하기
  - 현재 `app.py`는 요청 JSON 값이 없거나 잘못되어도 바로 내부 함수로 넘깁니다.
  - 잘못된 요청은 `400 Bad Request`와 명확한 에러 메시지를 반환하도록 처리하는 것이 좋습니다.

- [x] `character.py`의 캐릭터명과 실제 폴더명 불일치 확인하기
  - 예: `미운아기오리` 폴더 구조와 `character_quizzes`의 `"미운 아기 오리"` 키가 다릅니다.
  - API 요청값, 딕셔너리 키, 실제 디렉토리명을 하나의 기준으로 맞춰야 합니다.

- [x] `KeyError` 방어 처리 추가하기
  - `character_prompts[book_title][character_name]`
  - `character_quizzes[book_title][character_name]`
  - 현재는 없는 작품/캐릭터가 들어오면 서버 오류가 날 수 있습니다.

- [x] MariaDB 연결 실패 처리 추가하기
  - `get_db_connection()` 실패 시 서버가 바로 예외로 터질 수 있습니다.
  - 연결 실패, 테이블 없음, 쿼리 실패를 잡아 JSON 에러로 반환하도록 처리하면 디버깅이 쉬워집니다.

## 간단히 정리 가능한 부분

- [x] `app.py`의 `bot.load_chat_history(session_id=session_id)` 호출 정리하기
  - 현재 반환값을 사용하지 않고 있습니다.
  - 실제 요약은 `get_answer()` 내부에서 다시 `load_chat_history()`를 호출합니다.
  - 중복 호출이므로 제거해도 동작상 영향이 거의 없습니다.

- [x] `initialize_retriever(db, k=3)`의 `k` 인자 반영하기
  - 함수 인자로 `k`를 받지만 `search_kwargs`에 사용하지 않습니다.
  - `search_kwargs={"score_threshold": 0.7, "k": k}` 형태로 반영할 수 있습니다.

- [x] `fetch_data()` 반환 타입을 프롬프트에 맞게 정리하기
  - 현재 리스트를 그대로 프롬프트에 넣습니다.
  - `"\n".join(results)` 형태의 문자열로 바꾸면 LLM 입력이 더 안정적입니다.

- [x] `quiz.py` 서술형 JSON 출력 프롬프트 보강하기
  - 현재 JSON 예시가 중괄호 없이 작성되어 있습니다.
  - LLM이 순수 JSON이 아닌 텍스트를 반환하면 `json.loads()`에서 실패할 수 있습니다.

- [x] `json.loads(chain.invoke(...))` 예외 처리 추가하기
  - 서술형 퀴즈 평가에서 LLM 응답이 깨지면 서버 오류가 납니다.
  - `try/except json.JSONDecodeError`로 사용자에게 안정적인 에러를 반환하는 것이 좋습니다.

- [x] 로그 출력 정리하기
  - `print()` 로그가 많고 운영/개발 구분이 없습니다.
  - 최소한 `logging` 모듈로 바꾸면 디버깅과 배포 환경 관리가 쉬워집니다.

## 보안 및 설정

- [x] `.env` 파일 Git 추적 여부 확인하기
  - `.env`에는 OpenAI API 키와 DB 비밀번호가 들어갈 가능성이 큽니다.
  - `.gitignore`에 `.env`, `venv/`, `__pycache__/`가 포함되어야 합니다.

- [x] Dockerfile 한글 경로 깨짐 수정하기
  - 현재 Dockerfile의 여러 `COPY` 경로가 깨져 보입니다.
  - UTF-8로 다시 저장하고 실제 폴더명 기준으로 정리해야 Docker 빌드가 안정적입니다.

- [x] DB 접속 기본값 정리하기
  - Dockerfile에 `DB_PASSWORD=1234` 같은 기본값이 있습니다.
  - 민감정보는 Dockerfile보다 환경변수 주입 방식으로 관리하는 것이 안전합니다.

## 데이터 및 유지보수

- [ ] 중복 데이터 디렉토리 정리하기
  - 예: `성냥팔이소녀/data`와 `성냥팔이소녀/성냥팔이소녀/data`가 함께 존재합니다.
  - 앱이 어느 경로를 기준으로 삼는지 정한 뒤 중복을 줄이는 것이 좋습니다.

- [ ] Chroma 생성 스크립트 공통화하기
  - 일부 폴더에 같은 `chroma.py`가 복사되어 있습니다.
  - 공통 스크립트 하나에서 `book_title`, `character_name`을 인자로 받아 처리하게 만들면 유지보수가 쉬워집니다.

- [x] `chatbot.py`와 `chatbot_sql.py` 역할 정리하기
  - `chatbot.py`는 JSON 파일 저장 방식, `chatbot_sql.py`는 MariaDB 저장 방식입니다.
  - 실제 사용하는 방식을 기준으로 파일명을 명확히 하거나 README에 용도를 적는 것이 좋습니다.

- [ ] `chat_history.json` 샘플/실데이터 구분하기
  - 현재 대화 기록 파일이 포함되어 있습니다.
  - 샘플이면 이름을 바꾸고, 실사용 데이터면 Git에서 제외하는 것이 좋습니다.

## 문서화하면 좋은 실행 정보

- [x] README 추가하기
  - 프로젝트 설명
  - 필요한 환경변수
  - MariaDB 테이블 스키마
  - Flask 실행 명령
  - API 요청/응답 예시

- [x] API 예시 정리하기
  - `POST /`
  - `POST /quiz_question`
  - `POST /evaluate_quiz`
  - 올바른 `book_title`, `character_name` 목록

- [x] MariaDB `conversations` 테이블 생성 SQL 추가하기
  - 코드상 필요한 컬럼은 `session_id`, `role`, `content`, `created_at`입니다.
  - 새 환경에서 바로 실행할 수 있게 SQL 파일이나 README에 명시하면 좋습니다.
