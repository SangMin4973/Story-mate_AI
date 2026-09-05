# Story-mate AI

동화와 소설 속 캐릭터의 관점으로 대화하고, 작품별 퀴즈를 제공하는 Flask 기반 AI 서버입니다. LangChain, OpenAI, Chroma DB, MariaDB를 사용합니다.

## 주요 기능

- 캐릭터 역할 대화 API
- OX, 객관식, 서술형 퀴즈 API
- 작품/캐릭터별 Chroma DB 검색 기반 답변 생성
- MariaDB 기반 세션별 대화 기록 저장

## 실행 준비

```powershell
cd storymate
.\venv\Scripts\activate
```

필요한 환경변수는 `storymate/.env`에 설정합니다.

```env
OPENAI_API_KEY=your_openai_api_key
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_db_password
DB_NAME=chatdb
DB_CHARSET=utf8mb4
```

DB 테이블은 [schema.sql](schema.sql)을 참고해 생성합니다.

## 서버 실행

기존 Flask 서버:

```powershell
cd storymate
.\venv\Scripts\activate
python app.py
```

FastAPI 웹 화면:

```powershell
cd storymate
.\venv\Scripts\activate
uvicorn fastapi_web:app --host 0.0.0.0 --port 8000 --reload
```

기본 주소는 `http://localhost:5000`입니다.
FastAPI 웹 화면은 `http://localhost:8000`에서 확인할 수 있습니다.

## API

### POST /

캐릭터와 대화합니다.

```json
{
  "session_id": "test_1",
  "book_title": "운수좋은날",
  "character_name": "김첨지",
  "query": "너는 누구야?"
}
```

### POST /quiz_question

퀴즈 질문을 가져옵니다.

```json
{
  "book_title": "운수좋은날",
  "character_name": "김첨지",
  "quiz_type": "ox"
}
```

`quiz_type`은 `ox`, `multiple_choice`, `essay` 중 하나입니다.

### POST /evaluate_quiz

퀴즈 답안을 평가합니다.

```json
{
  "book_title": "운수좋은날",
  "character_name": "김첨지",
  "quiz_type": "ox",
  "user_answer": "O"
}
```

## 사용 가능한 작품/캐릭터

- `운수좋은날` / `김첨지`
- `인어공주` / `인어공주`
- `성냥팔이소녀` / `성냥팔이소녀`
- `엄지공주` / `엄지공주`
- `동백꽃` / `화자`, `점순이`
- `시골쥐서울구경` / `시골쥐`
- `미운아기오리` / `미운아기오리`, `미운 아기 오리`
- `메밀꽃필무렵` / `허생원`
- `날개` / `화자`
- `심봉사` / `심봉사`

캐릭터명은 공백 차이를 일부 보정합니다. 예를 들어 `미운아기오리`와 `미운 아기 오리`는 같은 이름으로 처리됩니다.

## 파일 역할

- `app.py`: Flask API 진입점
- `chatbot_sql.py`: MariaDB 대화 기록을 사용하는 채팅 로직
- `chatbot.py`: JSON 파일 대화 기록을 사용하는 이전/로컬 테스트용 채팅 로직
- `quiz.py`: 퀴즈 질문 조회와 답안 평가
- `template.py`: 캐릭터 대화 프롬프트 생성
- `character.py`: 캐릭터 프롬프트와 퀴즈 데이터
- `utils.py`: Chroma, retriever, OpenAI 모델 초기화 공통 함수
