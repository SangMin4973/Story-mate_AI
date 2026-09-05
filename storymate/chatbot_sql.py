import os
import logging
import pymysql
from dotenv import load_dotenv
from character import character_prompts

# .env 파일 로드
load_dotenv()

# 환경 변수 가져오기
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")  # 기본값 utf8mb4

# MariaDB 연결 함수
def get_db_connection():
    missing_envs = [
        name for name, value in {
            "DB_HOST": DB_HOST,
            "DB_USER": DB_USER,
            "DB_PASSWORD": DB_PASSWORD,
            "DB_NAME": DB_NAME,
        }.items()
        if not value
    ]
    if missing_envs:
        raise ValueError(f"DB 환경변수가 누락되었습니다: {', '.join(missing_envs)}")

    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset=DB_CHARSET,
        cursorclass=pymysql.cursors.DictCursor
    )


from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# 모듈에서 필요한 함수들을 임포트
from utils import (
    initialize_chroma_db, fetch_data, initialize_retriever, initialize_llm,
    find_embedding_base_path, resolve_key
)
from template import get_character_template

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)




class ChatBot:

    # ✅ ChatBot 클래스 초기화
    def __init__(self, character_name, book_title, retrieval_mode: str = "default"):
        resolved_book_title = resolve_key(character_prompts, book_title)
        if not resolved_book_title:
            raise ValueError(f"'{book_title}' 작품 정보를 찾을 수 없습니다.")
        resolved_character_name = resolve_key(character_prompts[resolved_book_title], character_name)
        if not resolved_character_name:
            raise ValueError(f"'{book_title}'의 '{character_name}' 캐릭터 정보를 찾을 수 없습니다.")

        # 2) DB 경로 설정
        base_path = find_embedding_base_path(BASE_DIR, resolved_book_title, resolved_character_name)
        self.character_name = resolved_character_name
        self.book_title = resolved_book_title
        self.retrieval_mode = retrieval_mode
        self.final_retriever = None

        # 3) DB & 리트리버 초기화
        if retrieval_mode == "final_rerank":
            from final_retriever import FinalRerankRetriever

            self.final_retriever = FinalRerankRetriever(
                base_dir=BASE_DIR,
                book_title=resolved_book_title,
                character_name=resolved_character_name,
            )
        elif retrieval_mode == "default":
            self.q_db = initialize_chroma_db(f"{base_path}/예상질문_chroma_db")
            self.e_db = initialize_chroma_db(f"{base_path}/인물평가_chroma_db")
            self.n_db = initialize_chroma_db(f"{base_path}/전문_chroma_db")
            self.c_db = initialize_chroma_db(f"{base_path}/인물특성_chroma_db")

            self.q_retriever = initialize_retriever(self.q_db)
            self.e_retriever = initialize_retriever(self.e_db)
            self.n_retriever = initialize_retriever(self.n_db)
            self.c_retriever = initialize_retriever(self.c_db)
        else:
            raise ValueError(f"지원하지 않는 retrieval_mode입니다: {retrieval_mode}")

        # 4) 템플릿 & LLM
        self.prompt_template = get_character_template(resolved_book_title, resolved_character_name)
        self.llm = initialize_llm(model_name="gpt-4o")

        # 5) 체인 결합 (PromptTemplate → LLM → StrOutputParser)
        self.chain = self.prompt_template | self.llm | StrOutputParser()




    # ✅ DB에서 대화 기록 불러오기
    def load_chat_history(self, session_id):
        """
        특정 session_id의 대화 기록을 MariaDB에서 불러옴
        """
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT role, content FROM conversations WHERE session_id = %s ORDER BY created_at", (session_id,))
            return cursor.fetchall()
        finally:
            if conn:
                conn.close()



    # ✅ DB에 대화 기록 저장
    def save_chat_history(self, session_id, role, content):
        """
        MariaDB에 새로운 대화 내용을 저장
        """
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, role, content)
            )
            conn.commit()
        finally:
            if conn:
                conn.close()



    # ✅ 새로운 대화 추가 (사용자 → 챗봇)
    def add_conversation(self, session_id, user_query, response):
        """
        새로운 대화를 MariaDB에 저장
        """
        self.save_chat_history(session_id, "human", user_query)
        self.save_chat_history(session_id, "ai", response)



    # ✅ 대화 내용을 요약하는 함수
    def format_chat_history(self, history):
        role_names = {
            "human": "사용자",
            "user": "사용자",
            "ai": self.character_name,
            "assistant": self.character_name,
        }
        return "\n".join(
            f"{role_names.get(msg.get('role'), msg.get('role', 'unknown'))}: {msg.get('content', '')}"
            for msg in history
        )


    def summarize_history(self, session_id):
        """
        특정 세션의 대화 기록을 MariaDB에서 불러와 요약하는 함수
        """

        history = self.load_chat_history(session_id)


        if not history:
            return "이전 대화 기록이 없습니다."

        # 요약할 텍스트 변환 (role을 붙여서 정리)
        conversation_text = self.format_chat_history(history)

        # 요약 프롬프트 설정
        summary_prompt = (
        """
        [이전 대화 요약]
        - 마크다운 형식으로 작성합니다.
        - 사용자의 정보와 대화 주제를 강조하여 chat_history를 요약합니다.

        chat_history : {conversation_text}"""
        )

        # 요약 실행
        summary_chain = ChatPromptTemplate.from_template(summary_prompt) | self.llm | StrOutputParser()
        summary = summary_chain.invoke({"conversation_text": conversation_text})

        logger.info("[대화 요약]: %s", summary)
        return summary 



    # ✅ 최종 답변 생성 함수
    def get_answer(self, session_id: str, user_query: str, chat_history_override=None, save_history: bool = True) -> str:
        """
        세션 ID 기반으로 DB 검색 후, 캐릭터 템플릿과 LLM으로 답변 생성
            """
        
        if not isinstance(user_query, str) or not user_query.strip():
            return "오류: 질문이 없습니다."

        logger.info("get_answer()에서 user_query 확인: %s (type: %s)", user_query, type(user_query))
        
        # 각 DB에서 context를 검색
        if self.retrieval_mode == "final_rerank":
            contexts = self.final_retriever.retrieve_contexts(user_query)
            question_context = contexts["context_doc4"]
            evaluate_context = contexts["context_doc2"]
            novel_context = contexts["context_doc1"]
            character_context = contexts["context_doc3"]
        else:
            question_context  = fetch_data(self.q_retriever, user_query)
            evaluate_context  = fetch_data(self.e_retriever, user_query)
            novel_context     = fetch_data(self.n_retriever, user_query)
            character_context = fetch_data(self.c_retriever, user_query)

        # 이전 대화 내용 요약
        if chat_history_override is None:
            summarized_history = self.summarize_history(session_id)
        elif chat_history_override:
            summarized_history = self.format_chat_history(chat_history_override)
        else:
            summarized_history = "이전 대화 기록이 없습니다."

        # 체인에 넣을 input_data
        input_data = {
            "context_doc1": novel_context,
            "context_doc2": evaluate_context,
            "context_doc3": character_context,
            "context_doc4": question_context,
            "query": user_query,
            "chat_history": summarized_history,
        }

        # 체인 실행
        response = self.chain.invoke(input_data)

        # 대화 저장
        if save_history:
            self.add_conversation(session_id, user_query, response)

        return response
