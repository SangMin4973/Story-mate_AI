import json
import logging
from typing import Any

import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from chatbot_sql import ChatBot
from quiz import evaluate_quiz_answer, get_quiz_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Story-mate AI")


class ChatRequest(BaseModel):
    session_id: str
    book_title: str
    character_name: str
    query: str


class QuizQuestionRequest(BaseModel):
    book_title: str
    character_name: str
    quiz_type: str


class EvaluateQuizRequest(BaseModel):
    book_title: str
    character_name: str
    quiz_type: str
    user_answer: str


def get_error_status(error_message: str) -> int:
    if "찾을 수 없습니다" in error_message:
        return 404
    return 400


def parse_quiz_result(result: Any) -> dict:
    if isinstance(result, dict):
        return result

    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"JSONDecodeError: {result}") from exc

        if isinstance(parsed, dict):
            return parsed

    raise HTTPException(status_code=500, detail="Unknown return type from evaluate_quiz_answer.")


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(
        """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Story-mate AI</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, "Noto Sans KR", sans-serif;
      background: #f5f7fb;
      color: #1f2937;
    }
    header {
      padding: 18px 24px;
      background: #263238;
      color: white;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 700;
    }
    main {
      max-width: 1080px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 18px;
    }
    section {
      background: white;
      border: 1px solid #d9e0ea;
      border-radius: 8px;
      padding: 16px;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 16px;
    }
    label {
      display: block;
      margin: 12px 0 6px;
      font-size: 13px;
      font-weight: 700;
      color: #374151;
    }
    input, select, textarea, button {
      width: 100%;
      font: inherit;
      border-radius: 6px;
    }
    input, select, textarea {
      border: 1px solid #c9d3df;
      padding: 10px;
      background: white;
    }
    textarea {
      min-height: 86px;
      resize: vertical;
    }
    button {
      margin-top: 12px;
      border: 0;
      padding: 11px 12px;
      background: #2f6fed;
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary {
      background: #455a64;
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .chat-log {
      height: 520px;
      overflow: auto;
      border: 1px solid #d9e0ea;
      border-radius: 8px;
      background: #f9fbfd;
      padding: 12px;
    }
    .message {
      margin-bottom: 10px;
      padding: 10px 12px;
      border-radius: 8px;
      white-space: pre-wrap;
      line-height: 1.5;
    }
    .user {
      background: #e3f2fd;
      margin-left: 48px;
    }
    .bot {
      background: #eef2f7;
      margin-right: 48px;
    }
    .error {
      background: #fff1f2;
      color: #b42318;
      border: 1px solid #fecdd3;
    }
    .quiz-result {
      margin-top: 12px;
      min-height: 80px;
      padding: 10px;
      border: 1px solid #d9e0ea;
      border-radius: 8px;
      background: #f9fbfd;
      white-space: pre-wrap;
    }
    @media (max-width: 820px) {
      main {
        grid-template-columns: 1fr;
        padding: 14px;
      }
      .chat-log { height: 420px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Story-mate AI</h1>
    <span>FastAPI</span>
  </header>
  <main>
    <section>
      <h2>설정</h2>
      <label for="sessionId">세션 ID</label>
      <input id="sessionId" value="test_1" />

      <label for="bookTitle">작품</label>
      <select id="bookTitle">
        <option>운수좋은날</option>
        <option>인어공주</option>
        <option>성냥팔이소녀</option>
        <option>엄지공주</option>
        <option>동백꽃</option>
        <option>시골쥐서울구경</option>
        <option>미운아기오리</option>
        <option>메밀꽃필무렵</option>
        <option>날개</option>
        <option>심봉사</option>
      </select>

      <label for="characterName">캐릭터</label>
      <input id="characterName" value="김첨지" />

      <h2 style="margin-top: 22px;">퀴즈</h2>
      <label for="quizType">유형</label>
      <select id="quizType">
        <option value="ox">OX</option>
        <option value="multiple_choice">객관식</option>
        <option value="essay">서술형</option>
      </select>
      <button class="secondary" id="loadQuizBtn">퀴즈 불러오기</button>
      <label for="quizAnswer">답안</label>
      <textarea id="quizAnswer" placeholder="답을 입력하세요"></textarea>
      <button class="secondary" id="evaluateQuizBtn">답안 평가</button>
      <div id="quizResult" class="quiz-result"></div>
    </section>

    <section>
      <h2>캐릭터 대화</h2>
      <div id="chatLog" class="chat-log"></div>
      <label for="query">질문</label>
      <textarea id="query" placeholder="캐릭터에게 질문하세요"></textarea>
      <button id="sendBtn">보내기</button>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);

    function payload(extra = {}) {
      return {
        session_id: $("sessionId").value.trim(),
        book_title: $("bookTitle").value.trim(),
        character_name: $("characterName").value.trim(),
        ...extra
      };
    }

    async function postJson(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || data.error || JSON.stringify(data));
      }
      return data;
    }

    function addMessage(text, type) {
      const el = document.createElement("div");
      el.className = "message " + type;
      el.textContent = text;
      $("chatLog").appendChild(el);
      $("chatLog").scrollTop = $("chatLog").scrollHeight;
    }

    function setQuizResult(text, isError = false) {
      $("quizResult").className = "quiz-result" + (isError ? " error" : "");
      $("quizResult").textContent = text;
    }

    $("sendBtn").addEventListener("click", async () => {
      const query = $("query").value.trim();
      if (!query) return;
      $("sendBtn").disabled = true;
      addMessage(query, "user");
      $("query").value = "";

      try {
        const data = await postJson("/api/chat", payload({ query }));
        addMessage(data.response, "bot");
      } catch (error) {
        addMessage(error.message, "error");
      } finally {
        $("sendBtn").disabled = false;
      }
    });

    $("loadQuizBtn").addEventListener("click", async () => {
      $("loadQuizBtn").disabled = true;
      try {
        const data = await postJson("/api/quiz_question", payload({
          quiz_type: $("quizType").value
        }));
        setQuizResult(data.quiz);
      } catch (error) {
        setQuizResult(error.message, true);
      } finally {
        $("loadQuizBtn").disabled = false;
      }
    });

    $("evaluateQuizBtn").addEventListener("click", async () => {
      $("evaluateQuizBtn").disabled = true;
      try {
        const data = await postJson("/api/evaluate_quiz", payload({
          quiz_type: $("quizType").value,
          user_answer: $("quizAnswer").value.trim()
        }));
        setQuizResult(JSON.stringify(data, null, 2));
      } catch (error) {
        setQuizResult(error.message, true);
      } finally {
        $("evaluateQuizBtn").disabled = false;
      }
    });

    $("query").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        $("sendBtn").click();
      }
    });
  </script>
</body>
</html>
        """
    )


@app.post("/api/chat")
def chat_api(data: ChatRequest):
    logger.info(
        "채팅 요청 받음 - 세션: %s, 책 이름: %s, 캐릭터: %s",
        data.session_id,
        data.book_title,
        data.character_name,
    )

    try:
        bot = ChatBot(book_title=data.book_title, character_name=data.character_name)
        response_text = bot.get_answer(user_query=data.query, session_id=data.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except pymysql.MySQLError as exc:
        raise HTTPException(status_code=500, detail="데이터베이스 처리 중 오류가 발생했습니다.") from exc
    except Exception as exc:
        logger.exception("채팅 처리 오류: %s", exc)
        raise HTTPException(status_code=500, detail="채팅 처리 중 오류가 발생했습니다.") from exc

    return {
        "session_id": data.session_id,
        "book_title": data.book_title,
        "character_name": data.character_name,
        "response": response_text,
    }


@app.post("/api/quiz_question")
def quiz_question_api(data: QuizQuestionRequest):
    question = get_quiz_question(
        book_title=data.book_title,
        character_name=data.character_name,
        quiz_type=data.quiz_type,
    )

    if "찾을 수 없습니다" in question or "존재하지 않습니다" in question:
        raise HTTPException(status_code=get_error_status(question), detail=question)

    return {
        "character_name": data.character_name,
        "quiz_type": data.quiz_type,
        "quiz": question,
    }


@app.post("/api/evaluate_quiz")
def evaluate_quiz_api(data: EvaluateQuizRequest):
    result = evaluate_quiz_answer(
        book_title=data.book_title,
        character_name=data.character_name,
        quiz_type=data.quiz_type,
        user_answer=data.user_answer,
    )
    parsed = parse_quiz_result(result)

    if "error" in parsed:
        raise HTTPException(status_code=get_error_status(parsed["error"]), detail=parsed["error"])

    return parsed


@app.post("/")
def legacy_chat_api(data: ChatRequest):
    return chat_api(data)


@app.post("/quiz_question")
def legacy_quiz_question_api(data: QuizQuestionRequest):
    return quiz_question_api(data)


@app.post("/evaluate_quiz")
def legacy_evaluate_quiz_api(data: EvaluateQuizRequest):
    return evaluate_quiz_api(data)
