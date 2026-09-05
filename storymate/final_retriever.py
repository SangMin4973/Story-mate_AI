import math
import re
from collections import Counter
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from utils import normalize_name

DOC_DB_NAMES = {
    "doc1": "전문_chroma_db",
    "doc2": "인물평가_chroma_db",
    "doc3": "인물특성_chroma_db",
}

TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    words = [token.lower() for token in TOKEN_PATTERN.findall(str(text or ""))]
    compact = "".join(words)
    bigrams = [compact[index:index + 2] for index in range(max(len(compact) - 1, 0))]
    return words + bigrams


def split_ids(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


class BM25Index:
    def __init__(self, documents: list[dict], k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(document["text"]) for document in documents]
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0
        self.term_frequencies = [Counter(tokens) for tokens in self.doc_tokens]
        self.doc_frequencies = Counter()

        for tokens in self.doc_tokens:
            self.doc_frequencies.update(set(tokens))

    def idf(self, token: str) -> float:
        doc_count = len(self.documents)
        containing_count = self.doc_frequencies.get(token, 0)
        return math.log(1 + (doc_count - containing_count + 0.5) / (containing_count + 0.5))

    def score_document(self, query_tokens: list[str], index: int) -> float:
        score = 0.0
        frequencies = self.term_frequencies[index]
        doc_length = self.doc_lengths[index]

        for token in query_tokens:
            frequency = frequencies.get(token, 0)
            if not frequency:
                continue

            denominator = frequency + self.k1 * (
                1 - self.b + self.b * doc_length / max(self.avg_doc_length, 1)
            )
            score += self.idf(token) * frequency * (self.k1 + 1) / denominator
        return score

    def search(self, query: str, k: int) -> list[dict]:
        query_tokens = tokenize(query)
        scored = []
        for index, document in enumerate(self.documents):
            score = self.score_document(query_tokens, index)
            if score <= 0:
                continue
            scored.append({**document, "score": score, "retrieval_source": "bm25"})

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ImportError(
                "final_rerank 검색을 사용하려면 sentence-transformers가 필요합니다. "
                "`pip install sentence-transformers`를 실행하세요."
            ) from exc

        self.model_name = model_name
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates: list[dict], k: int) -> list[dict]:
        pairs = [(query, candidate["text"]) for candidate in candidates]
        scores = self.model.predict(pairs)
        reranked = []

        for candidate, score in zip(candidates, scores):
            reranked.append({
                **candidate,
                "hybrid_score": candidate.get("score"),
                "rerank_score": float(score),
                "score": float(score),
                "reranker_model": self.model_name,
            })

        reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return dedupe_candidates(reranked, k)


def find_chunk_experiment_path(base_dir: str, book_title: str, character_name: str, experiment_name: str) -> Path:
    normalized_character_name = normalize_name(character_name)
    candidates = [
        Path(base_dir) / book_title / character_name / "data" / "chunk_experiments" / experiment_name,
        Path(base_dir) / book_title / normalized_character_name / "data" / "chunk_experiments" / experiment_name,
        Path(base_dir) / book_title / "data" / "chunk_experiments" / experiment_name,
    ]

    for path in candidates:
        if path.is_dir():
            return path

    raise FileNotFoundError(f"실험용 Chroma 경로를 찾을 수 없습니다: {candidates[0]}")


def dedupe_candidates(candidates: list[dict], k: int) -> list[dict]:
    deduped = []
    seen = set()
    for candidate in candidates:
        dedup_key = candidate.get("chunk_id") or (
            candidate["doc_id"],
            tuple(candidate.get("source_chunk_ids", [])),
            candidate["text"][:120],
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        deduped.append(candidate)
        if len(deduped) >= k:
            break
    return deduped


def reciprocal_rank_fusion(vector_rows: list[dict], bm25_rows: list[dict], k: int):
    fused = {}

    def add_rows(rows: list[dict], source: str):
        for rank, row in enumerate(rows, start=1):
            key = row.get("chunk_id") or (row["doc_id"], tuple(row.get("source_chunk_ids", [])))
            if key not in fused:
                fused[key] = {**row, "rrf_score": 0.0, "fusion_sources": []}
            fused[key]["rrf_score"] += 1.0 / (60 + rank)
            fused[key]["fusion_sources"].append(source)

    add_rows(vector_rows, "vector")
    add_rows(bm25_rows, "bm25")

    candidates = list(fused.values())
    candidates.sort(key=lambda item: item["rrf_score"], reverse=True)
    for row in candidates:
        row["score"] = row["rrf_score"]
    return dedupe_candidates(candidates, k)


class FinalRerankRetriever:
    def __init__(
        self,
        base_dir: str,
        book_title: str,
        character_name: str,
        experiment_name: str = "chunk_larger",
        hybrid_pool_size: int = 20,
        final_k: int = 5,
        per_doc_k: int = 5,
        reranker_model: str = "BAAI/bge-reranker-v2-m3",
    ):
        self.hybrid_pool_size = hybrid_pool_size
        self.final_k = final_k
        self.per_doc_k = per_doc_k
        self.base_path = find_chunk_experiment_path(base_dir, book_title, character_name, experiment_name)
        self.embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
        self.databases = self._load_databases()
        self.documents = self._load_documents()
        self.bm25_index = BM25Index(self.documents)
        self.reranker = CrossEncoderReranker(reranker_model)

    def _load_databases(self) -> dict[str, Chroma]:
        databases = {}
        for doc_id, db_name in DOC_DB_NAMES.items():
            db_path = self.base_path / db_name
            if db_path.is_dir():
                databases[doc_id] = Chroma(
                    persist_directory=str(db_path),
                    embedding_function=self.embeddings,
                )

        if not databases:
            raise FileNotFoundError(f"사용 가능한 Chroma DB를 찾을 수 없습니다: {self.base_path}")
        return databases

    def _load_documents(self) -> list[dict]:
        documents = []
        for doc_id, db in self.databases.items():
            data = db.get(include=["documents", "metadatas"])
            ids = data.get("ids", [])
            texts = data.get("documents", [])
            metadatas = data.get("metadatas", [])

            for index, text in enumerate(texts):
                metadata = metadatas[index] or {}
                chunk_id = metadata.get("chunk_id") or ids[index]
                documents.append({
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "source_chunk_ids": split_ids(metadata.get("source_chunk_ids", chunk_id)),
                    "text": text or "",
                    "metadata": metadata,
                })
        return documents

    def vector_search(self, query: str, k: int) -> list[dict]:
        candidates = []
        for doc_id, db in self.databases.items():
            try:
                results = db.similarity_search_with_relevance_scores(query, k=self.per_doc_k)
            except AttributeError:
                results = [(doc, None) for doc in db.similarity_search(query, k=self.per_doc_k)]

            for rank_in_doc, (doc, score) in enumerate(results, start=1):
                metadata = getattr(doc, "metadata", {}) or {}
                chunk_id = metadata.get("chunk_id")
                candidates.append({
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "source_chunk_ids": split_ids(metadata.get("source_chunk_ids", chunk_id)),
                    "text": getattr(doc, "page_content", ""),
                    "score": score if score is not None else 0,
                    "rank_in_doc": rank_in_doc,
                    "metadata": metadata,
                    "retrieval_source": "vector",
                })

        candidates.sort(key=lambda item: item["score"], reverse=True)
        return dedupe_candidates(candidates, k)

    def retrieve(self, query: str) -> list[dict]:
        vector_rows = self.vector_search(query, self.hybrid_pool_size)
        bm25_rows = self.bm25_index.search(query, self.hybrid_pool_size)
        hybrid_candidates = reciprocal_rank_fusion(vector_rows, bm25_rows, self.hybrid_pool_size)
        return self.reranker.rerank(query, hybrid_candidates, self.final_k)

    def retrieve_contexts(self, query: str) -> dict[str, str]:
        retrieved = self.retrieve(query)
        grouped = {"doc1": [], "doc2": [], "doc3": []}

        for item in retrieved:
            if item["doc_id"] in grouped:
                grouped[item["doc_id"]].append(item["text"])

        return {
            "context_doc1": "\n\n".join(grouped["doc1"]),
            "context_doc2": "\n\n".join(grouped["doc2"]),
            "context_doc3": "\n\n".join(grouped["doc3"]),
            "context_doc4": "",
            "retrieved": retrieved,
        }
