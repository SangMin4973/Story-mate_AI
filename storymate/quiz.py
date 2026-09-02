import json
import logging
import os
from character import character_quizzes, character_prompts
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import SystemMessagePromptTemplate,  HumanMessagePromptTemplate, ChatPromptTemplate
from utils import (
    initialize_chroma_db, fetch_data, initialize_retriever, initialize_llm,
    find_embedding_base_path, resolve_key
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)


def get_quiz_question(book_title: str, character_name: str, quiz_type: str):
    """
    특정 캐릭터의 퀴즈를 가져오는 함수. 
    퀴즈 질문(문제)만 문자열로 반환합니다.

    입력:
    - character_name (str): 퀴즈를 진행할 캐릭터 이름
    - quiz_type (str): 퀴즈 유형 ('ox', 'multiple_choice', 'essay')

    출력:
    - 퀴즈의 질문(문제)만 문자열로 반환
    """
    resolved_book_title = resolve_key(character_quizzes, book_title)
    if not resolved_book_title:
        return f"'{book_title}' 작품의 퀴즈 데이터를 찾을 수 없습니다."
    resolved_character_name = resolve_key(character_quizzes[resolved_book_title], character_name)
    if not resolved_character_name:
        return f"'{character_name}'에 대한 퀴즈 데이터를 찾을 수 없습니다."

    # 캐릭터의 퀴즈 데이터 가져오기
    character_quiz = character_quizzes[resolved_book_title][resolved_character_name]

    # 캐릭터 정보가 없을 경우 예외처리
    if not character_quiz:
        return f"'{character_name}'에 대한 퀴즈 데이터를 찾을 수 없습니다."

    # 요청한 퀴즈 유형에 해당하는 데이터 가져오기
    quiz_data = character_quiz.get(quiz_type)

    # 퀴즈 유형이 없을 경우 예외처리
    if not quiz_data:
        return f"'{quiz_type}' 유형의 퀴즈가 존재하지 않습니다."

    # 퀴즈의 질문(문제)만 반환
    return quiz_data["question"]

def evaluate_quiz_answer(book_title: str, character_name: str, quiz_type: str, user_answer: str):
    """
    사용자가 제출한 퀴즈 답안을 평가하는 함수.

    입력:
    - character_name (str): 캐릭터 이름
    - quiz_type (str): 퀴즈 유형 ('ox', 'multiple_choice', 'essay')
    - user_answer (str): 사용자가 입력한 답변

    출력:
    - OX, 객관식: JSON (정답 여부 'correct' + 'response')
    - 서술형: 문자열(LLM 응답)만 반환
    """

    resolved_book_title = resolve_key(character_quizzes, book_title)
    if not resolved_book_title:
        return json.dumps({"error": f"'{book_title}' 작품의 퀴즈 데이터를 찾을 수 없습니다."}, ensure_ascii=False)
    resolved_quiz_character_name = resolve_key(character_quizzes[resolved_book_title], character_name)
    if not resolved_quiz_character_name:
        return json.dumps({"error": f"'{character_name}'에 대한 퀴즈 데이터를 찾을 수 없습니다."}, ensure_ascii=False)
    if not isinstance(user_answer, str) or not user_answer.strip():
        return json.dumps({"error": "사용자 답변이 없습니다."}, ensure_ascii=False)

    # ✅ 캐릭터의 퀴즈 데이터 가져오기
    character_quiz = character_quizzes[resolved_book_title][resolved_quiz_character_name]

    if not character_quiz:
        return json.dumps({"error": f"'{character_name}'에 대한 퀴즈 데이터를 찾을 수 없습니다."}, ensure_ascii=False)

    # ✅ 요청한 퀴즈 유형이 존재하는지 확인
    quiz_data = character_quiz.get(quiz_type)

    if not quiz_data:
        return json.dumps({"error": f"'{quiz_type}' 유형의 퀴즈가 존재하지 않습니다."}, ensure_ascii=False)

    # ✅ OX 및 객관식 정답 판별
    if quiz_type in ["ox", "multiple_choice"]:
        correct_answer = quiz_data["answer"]  # 정답
        is_correct = (user_answer.strip().lower() == correct_answer.lower())  # 판별
        response = quiz_data["correct_response"] if is_correct else quiz_data["incorrect_response"]

        # OX & 객관식은 JSON으로 정답 여부 + 반응만 반환
        return json.dumps({
            "quiz_type": quiz_type,
            "correct": is_correct,
            "response": response
        }, ensure_ascii=False)

    # ✅ 서술형(논술형) 문제는 LLM을 사용하여 평가
    elif quiz_type == "essay":
        # 1️⃣ 캐릭터 프롬프트 가져오기
        resolved_prompt_book_title = resolve_key(character_prompts, resolved_book_title)
        if not resolved_prompt_book_title:
            return json.dumps({"error": f"'{book_title}' 작품의 캐릭터 설정을 찾을 수 없습니다."}, ensure_ascii=False)

        resolved_prompt_character_name = resolve_key(character_prompts[resolved_prompt_book_title], character_name)
        if not resolved_prompt_character_name:
            return json.dumps({"error": f"'{character_name}'에 대한 캐릭터 설정을 찾을 수 없습니다."}, ensure_ascii=False)

        character_prompt = character_prompts[resolved_prompt_book_title][resolved_prompt_character_name]

        # 2️⃣ LLM 프롬프트 생성
        prompt_template = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(
                f"""
            user가 \"{quiz_data['question']}\" 에 대한 답변을 \"{user_answer}\" 라고 했습니다. 맞는지 틀린지 판단하고 보충 설명을 해주세요.

            [평가 지침]
            1. **당신은 {character_name}**입니다. {character_name}의 입장에서 성격과 특성을 고려해 답변하세요.
            2. 사용자의 답변이 정답에 어느 정도 부합하는지 스스로 분석하여 아래 3가지 중 하나로 판단:
            - "O": 맞음.
            - "C": 부분적으로 맞지만 보충 설명이 필요함
            - "X": 틀림.
            3. 반드시 한 가지로만 판별하세요.
            4. 왜 그런 판정을 했는지, 어떻게 보충/설명해야 하는지 서술해 주세요.

            [캐릭터 설정]
            {character_prompt}

            [관련 문서]
            - Doc1 (소설 내용) : {{context_doc1}}
            - Doc2 (인물 평가) : {{context_doc2}}
            - Doc3 (인물 특성) : {{context_doc3}}
            - Doc4 (예상 질문) : {{context_doc4}}

            [출력 형식]
            아래 **JSON 형식으로만 최종 답변을 작성하시오**. **불필요한 문장/토큰(예시: `,json)은 절대 추가하지 마세요.**

            {{
              "correct": "O 또는 C 또는 X",
              "response": "답변 설명을 여기에 작성"
            }}
            
            """
            ),
            HumanMessagePromptTemplate.from_template("{query}")
        ])

        # 3️⃣ LLM 호출
        llm = initialize_llm(model_name="gpt-4o")
        chain = prompt_template | llm | StrOutputParser()
        try:
            base_path = find_embedding_base_path(BASE_DIR, resolved_book_title, resolved_prompt_character_name)
        except FileNotFoundError as exc:
            return {
                "quiz_type": quiz_type,
                "error": str(exc)
            }

        # ✅ Chroma DB 초기화
        q_db = initialize_chroma_db(f"{base_path}/예상질문_chroma_db")
        e_db = initialize_chroma_db(f"{base_path}/인물평가_chroma_db")
        n_db = initialize_chroma_db(f"{base_path}/전문_chroma_db")
        c_db = initialize_chroma_db(f"{base_path}/인물특성_chroma_db")
        q_retriever = initialize_retriever(q_db)
        e_retriever = initialize_retriever(e_db)
        n_retriever = initialize_retriever(n_db)
        c_retriever = initialize_retriever(c_db)

        # ✅ Retrieval
        question_context  = fetch_data(q_retriever, user_answer)
        evaluate_context  = fetch_data(e_retriever, user_answer)
        novel_context     = fetch_data(n_retriever, user_answer)
        character_context = fetch_data(c_retriever, user_answer)  

        # ✅ Chain에 넘길 입력 데이터 구성
        input_data = {
            "context_doc1": novel_context,
            "context_doc2": evaluate_context,
            "context_doc3": character_context,
            "context_doc4": question_context,
            "query": user_answer,
        }

        # ✅ LLM으로부터 답변 받기
        try:
            response = json.loads(chain.invoke(input_data))
        except json.JSONDecodeError:
            return {
                "quiz_type": quiz_type,
                "error": "서술형 평가 응답이 JSON 형식이 아닙니다."
            }

        logger.debug("서술형 평가 프롬프트: %s", prompt_template.format(**input_data))
        response["quiz_type"] = quiz_type

        # 에세이(서술형)는 문자열(LLM 응답)만 반환
        return response

    # ✅ 잘못된 퀴즈 유형 입력 시
    return json.dumps({"error": f"잘못된 퀴즈 유형 '{quiz_type}' 입니다."}, ensure_ascii=False)
