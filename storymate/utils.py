import os
import logging
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

logger = logging.getLogger(__name__)


def normalize_name(value: str) -> str:
    return "".join(str(value).split())


def resolve_key(data: dict, key: str):
    if key in data:
        return key

    normalized_key = normalize_name(key)
    for candidate in data:
        if normalize_name(candidate) == normalized_key:
            return candidate

    return None


def find_embedding_base_path(base_dir: str, book_title: str, character_name: str, allow_book_fallback: bool = True) -> str:
    normalized_character_name = normalize_name(character_name)
    candidate_paths = [
        os.path.join(base_dir, book_title, character_name, "data", "embedding"),
        os.path.join(base_dir, book_title, normalized_character_name, "data", "embedding"),
    ]

    if allow_book_fallback:
        candidate_paths.append(os.path.join(base_dir, book_title, "data", "embedding"))

    for path in candidate_paths:
        if os.path.isdir(path):
            return path

    raise FileNotFoundError(f"임베딩 데이터 경로를 찾을 수 없습니다: {candidate_paths[0]}")


def initialize_chroma_db(persist_directory: str) -> Chroma:
    """
    Chroma DB를 초기화하여 반환합니다.
    """
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
    return Chroma(
        persist_directory=persist_directory,
        embedding_function=embeddings
    )


def fetch_data(retriever, query: str, max_docs: int = 2) -> str:
    """
    retriever.invoke(query) 결과에서 최대 max_docs개의 문서만 추출,
    각 문서의 page_content를 하나의 문자열로 반환
    """

    if not isinstance(query, str):
        logger.warning("query 타입 오류: %s, 값: %s", type(query), query)
        return ""
    
    docs = retriever.invoke(query)
    results = []
    for i, doc in enumerate(docs):
        if i >= max_docs:
            break
        results.append(doc.page_content)
    return "\n\n".join(results)

def initialize_retriever(db, k: int = 3):
    """
    Chroma DB로부터 Retriever를 생성하여 반환합니다.
    - search_type="similarity_score_threshold"
    - score_threshold=0.7
    """
    return db.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={"score_threshold": 0.7, "k": k}
    )

def initialize_llm(model_name: str = "gpt-4o", temperature: float = 0):
    """
    ChatOpenAI 모델을 초기화하고 반환합니다.
    """
    return ChatOpenAI(
        model=model_name,
        temperature=temperature
    )
