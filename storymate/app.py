from flask import Flask, request, jsonify
from chatbot_sql import ChatBot
from quiz import get_quiz_question, evaluate_quiz_answer
import json
import logging
import pymysql

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_json_data():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "요청 본문은 JSON 객체여야 합니다."}), 400)
    return data, None


def validate_required(data, required_fields):
    missing_fields = [
        field for field in required_fields
        if data.get(field) is None or str(data.get(field)).strip() == ""
    ]
    if missing_fields:
        return jsonify({
            "error": "필수 요청값이 누락되었습니다.",
            "missing_fields": missing_fields
        }), 400
    return None


def get_error_status(error_message):
    if "찾을 수 없습니다" in error_message:
        return 404
    return 400


@app.route('/', methods=['POST'])
def chat():
    # 여기부터는 POST 요청일 때 동작
    data, error_response = get_json_data()
    if error_response:
        return error_response

    validation_error = validate_required(data, ["session_id", "book_title", "character_name", "query"])
    if validation_error:
        return validation_error

    session_id = data.get("session_id")
    character_name = data.get("character_name")
    query = data.get("query")
    book_title = data.get("book_title")

    logger.info(
        "채팅 요청 받음 - 세션: %s, 책 이름: %s, 캐릭터: %s, 질문: %s",
        session_id,
        book_title,
        character_name,
        query,
    )

    try:
        bot = ChatBot(book_title=book_title, character_name=character_name)
        response_text = bot.get_answer(user_query=query, session_id=session_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except pymysql.MySQLError:
        return jsonify({"error": "데이터베이스 처리 중 오류가 발생했습니다."}), 500
    except Exception as exc:
        logger.exception("채팅 처리 오류: %s", exc)
        return jsonify({"error": "채팅 처리 중 오류가 발생했습니다."}), 500

    logger.info("챗봇 응답 - %s: %s", character_name, response_text)

    response_data = {
        "session_id": session_id,
        "book_title": book_title,
        "character_name": character_name,
        "response": response_text
    }

    logger.info("반환 데이터: %s", response_data)

    return jsonify(response_data)

@app.route('/quiz_question', methods=['POST'])
def quiz_question():
    """
    [POST /quiz_question]
    요청 예시:
    {
      "character_name": "김첨지",
      "quiz_type": "ox"
    }

    응답 예시:
    {
      "character_name": "김첨지",
      "quiz_type": "ox",
      "quiz": "퀴즈 질문 내용"
    }
    또는 에러 시:
    {
      "character_name": "김첨지",
      "quiz_type": "ox",
      "error": "'김첨지'에 대한 퀴즈 데이터를 찾을 수 없습니다."
    }
    """
    data, error_response = get_json_data()
    if error_response:
        return error_response

    validation_error = validate_required(data, ["book_title", "character_name", "quiz_type"])
    if validation_error:
        return validation_error

    character_name = data.get("character_name")
    book_title = data.get("book_title")
    quiz_type = data.get("quiz_type")
    question = get_quiz_question(book_title=book_title, character_name=character_name, quiz_type=quiz_type)

    # 에러 문자열(예: "'김첨지'에 대한 퀴즈 데이터를 찾을 수 없습니다.") 처리
    if "찾을 수 없습니다" in question or "존재하지 않습니다" in question:
        return jsonify({
            "character_name": character_name,
            "quiz_type": quiz_type,
            "error": question
        }), get_error_status(question)

    return jsonify({
        "character_name": character_name,
        "quiz_type": quiz_type,
        "quiz": question
    })


@app.route('/evaluate_quiz', methods=['POST'])
def evaluate_quiz():
    """
    [POST /evaluate_quiz]
    요청 예시:
    {
      "book_title": "운수좋은날",
      "character_name": "김첨지",
      "quiz_type": "essay",
      "user_answer": "~~~"
    }

    - OX/객관식:
      evaluate_quiz_answer() -> JSON 문자열('{"quiz_type":"ox","correct":true,"response":"..."}')
    - 에세이:
      evaluate_quiz_answer() -> 파이썬 딕셔너리({"quiz_type":"essay","correct":"C","response":"..."})
    - 에러:
      '{"error":"..."}' (JSON 문자열) 혹은 dict({"error":"..."})

    최종적으로 Flask는 반드시 JSON 형태로 응답해야 하므로,
    문자열이면 json.loads()로 파싱 후 반환,
    딕셔너리면 그대로 jsonify(...)로 반환.
    """
    data, error_response = get_json_data()
    if error_response:
        return error_response

    validation_error = validate_required(data, ["book_title", "character_name", "quiz_type", "user_answer"])
    if validation_error:
        return validation_error

    book_title = data.get("book_title")
    character_name = data.get("character_name")
    quiz_type = data.get("quiz_type")
    user_answer = data.get("user_answer")

    result = evaluate_quiz_answer(book_title=book_title, character_name=character_name, quiz_type=quiz_type, user_answer=user_answer)
    # result가 "서술형"이면 dict, "OX/객관식"이면 str(= JSON), 에러여도 str(=JSON)일 확률 높음

    # (A) 만약 이미 파이썬 딕셔너리라면 그대로 반환
    if isinstance(result, dict):
        # 바로 jsonify
        if "error" in result:
            return jsonify(result), get_error_status(result["error"])
        return jsonify(result)

    # (B) 문자열인 경우 (대부분 OX/객관식/에러) → JSON 파싱 시도
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            # parsed가 dict이면 정상 파싱된 것
            if isinstance(parsed, dict) and "error" in parsed:
                return jsonify(parsed), get_error_status(parsed["error"])
            return jsonify(parsed)
        except json.JSONDecodeError:
            # 만약 여기 걸리면, LLM이나 함수가 JSON 포맷을 깨트린 상황
            return jsonify({"error": "JSONDecodeError: " + result}), 500

    # (C) 그 외 유형(희박)
    return jsonify({"error": "Unknown return type from evaluate_quiz_answer."}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
