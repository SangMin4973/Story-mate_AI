import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
STORYMATE_DIR = EVAL_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(STORYMATE_DIR))

from evaluate_retriever import (  # noqa: E402
    load_evalset,
    split_ids,
    summarize,
    write_json,
    write_jsonl,
)
from run_chunk_experiment import (  # noqa: E402
    build_databases,
    retrieve as vector_retrieve,
    score_query,
    transform_corpus,
)
from utils import find_embedding_base_path  # noqa: E402

DATA_DIR = EVAL_DIR / "data"
RESULT_DIR = EVAL_DIR / "result" / "bm25_experiments"
DEFAULT_INPUT = DATA_DIR / "김첨지_검색기_평가셋_v1.xlsx"

TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    words = [token.lower() for token in TOKEN_PATTERN.findall(str(text or ""))]
    compact = "".join(words)
    bigrams = [compact[index:index + 2] for index in range(max(len(compact) - 1, 0))]
    return words + bigrams


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

            scored.append({
                **document,
                "score": score,
                "rank_in_doc": None,
                "metadata": {
                    "chunk_id": document["chunk_id"],
                    "doc_id": document["doc_id"],
                    "source_chunk_ids": "|".join(document["source_chunk_ids"]),
                    "chunk_type": document.get("chunk_type", ""),
                },
            })

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]


def flatten_transformed(transformed: dict[str, list[dict]], include_doc4: bool) -> list[dict]:
    documents = []
    for doc_id, rows in transformed.items():
        if doc_id == "doc4" and not include_doc4:
            continue
        for row in rows:
            documents.append({
                "doc_id": doc_id,
                "chunk_id": row["chunk_id"],
                "source_chunk_ids": row["source_chunk_ids"],
                "text": row["text"],
                "chunk_type": row.get("chunk_type", ""),
            })
    return documents


def dedupe_candidates(candidates: list[dict], k: int) -> list[dict]:
    deduped = []
    seen = set()
    for candidate in candidates:
        dedup_key = candidate.get("chunk_id") or (
            candidate["doc_id"],
            tuple(candidate["source_chunk_ids"]),
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        deduped.append(candidate)
        if len(deduped) >= k:
            break
    return deduped


def reciprocal_rank_fusion(vector_rows: list[dict], bm25_rows: list[dict], k: int, vector_weight: float, bm25_weight: float):
    fused = {}

    def add_rows(rows: list[dict], source: str, weight: float):
        for rank, row in enumerate(rows, start=1):
            key = row.get("chunk_id") or (row["doc_id"], tuple(row["source_chunk_ids"]))
            if key not in fused:
                fused[key] = {**row, "rrf_score": 0.0, "fusion_sources": []}
            fused[key]["rrf_score"] += weight / (60 + rank)
            fused[key]["fusion_sources"].append(source)

    add_rows(vector_rows, "vector", vector_weight)
    add_rows(bm25_rows, "bm25", bm25_weight)

    candidates = list(fused.values())
    candidates.sort(key=lambda item: item["rrf_score"], reverse=True)
    for row in candidates:
        row["score"] = row["rrf_score"]
    return dedupe_candidates(candidates, k)


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ImportError(
                "rerank 모드를 사용하려면 sentence-transformers가 필요합니다. "
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


def retrieve(args, query: str, transformed: dict[str, list[dict]], bm25_index: BM25Index, databases: dict | None):
    if args.mode == "bm25":
        return bm25_index.search(query, args.k)

    vector_rows = vector_retrieve(
        query=query,
        databases=databases,
        transformed=transformed,
        k=args.hybrid_pool_size,
        per_doc_k=args.per_doc_k,
    )
    bm25_rows = bm25_index.search(query, args.hybrid_pool_size)
    return reciprocal_rank_fusion(vector_rows, bm25_rows, args.k, args.vector_weight, args.bm25_weight)


def retrieve_with_reranker(
    args,
    query: str,
    transformed: dict[str, list[dict]],
    bm25_index: BM25Index,
    databases: dict,
    reranker: CrossEncoderReranker,
):
    vector_rows = vector_retrieve(
        query=query,
        databases=databases,
        transformed=transformed,
        k=args.hybrid_pool_size,
        per_doc_k=args.per_doc_k,
    )
    bm25_rows = bm25_index.search(query, args.hybrid_pool_size)
    hybrid_candidates = reciprocal_rank_fusion(
        vector_rows,
        bm25_rows,
        args.hybrid_pool_size,
        args.vector_weight,
        args.bm25_weight,
    )
    return reranker.rerank(query, hybrid_candidates, args.k)


def result_dir_name(args) -> str:
    if args.result_name:
        if any(separator in args.result_name for separator in ("/", "\\")):
            raise ValueError("--result-name에는 폴더 구분자를 포함할 수 없습니다.")
        return args.result_name
    return f"{args.chunk_experiment}_{args.mode}"


def run(args):
    queries, qrels, corpus = load_evalset(args.input)
    if args.limit:
        queries = queries[:args.limit]

    args.experiment = args.chunk_experiment
    transformed = transform_corpus(corpus, args)
    bm25_index = BM25Index(flatten_transformed(transformed, args.include_doc4), args.bm25_k1, args.bm25_b)

    databases = None
    if args.mode in {"hybrid", "rerank"}:
        current_embedding_path = Path(
            find_embedding_base_path(str(STORYMATE_DIR), args.book_title, args.character_name)
        )
        chroma_path = current_embedding_path.parent / "chunk_experiments" / args.chunk_experiment
        databases = build_databases(chroma_path, args.include_doc4)
    reranker = CrossEncoderReranker(args.reranker_model) if args.mode == "rerank" else None

    rows = []
    for index, query in enumerate(queries, start=1):
        query_id = query["query_id"]
        print(f"[{index}/{len(queries)}] {query_id} {query['category']}")
        if args.mode == "rerank":
            retrieved = retrieve_with_reranker(args, query["query"], transformed, bm25_index, databases, reranker)
        else:
            retrieved = retrieve(args, query["query"], transformed, bm25_index, databases)
        metrics = score_query(query, qrels.get(query_id, {}), retrieved, args.k_values)
        rows.append({
            "query_id": query_id,
            "category": query.get("category"),
            "subcategory": query.get("subcategory"),
            "difficulty": query.get("difficulty"),
            "query": query.get("query"),
            "primary_gold_chunk_ids": split_ids(query.get("primary_gold_chunk_ids")),
            "relevant_chunk_ids": split_ids(query.get("relevant_chunk_ids")),
            "target_doc_ids": split_ids(query.get("target_doc_ids")),
            "retrieved": retrieved,
            "metrics": metrics,
        })

    output_dir = RESULT_DIR / result_dir_name(args)
    detail_path = output_dir / "retriever_eval.jsonl"
    summary_path = output_dir / "retriever_eval_summary.json"
    manifest_path = output_dir / "manifest.json"

    write_jsonl(detail_path, rows)
    write_json(summary_path, summarize(rows, args.k_values))
    write_json(manifest_path, {
        "mode": args.mode,
        "chunk_experiment": args.chunk_experiment,
        "include_doc4": args.include_doc4,
        "k": args.k,
        "per_doc_k": args.per_doc_k,
        "hybrid_pool_size": args.hybrid_pool_size,
        "vector_weight": args.vector_weight,
        "bm25_weight": args.bm25_weight,
        "bm25_k1": args.bm25_k1,
        "bm25_b": args.bm25_b,
        "reranker_model": args.reranker_model if args.mode == "rerank" else None,
    })
    print(f"상세 결과 저장: {detail_path}")
    print(f"요약 결과 저장: {summary_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="BM25 단독, Vector+BM25 hybrid, reranker 검색기 평가")
    parser.add_argument("--mode", choices=["bm25", "hybrid", "rerank"], required=True)
    parser.add_argument("--chunk-experiment", default="chunk_larger")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--book-title", default="운수좋은날")
    parser.add_argument("--character-name", default="김첨지")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--per-doc-k", type=int, default=5)
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--group-size", type=int, default=2)
    parser.add_argument("--window-size", type=int, default=2)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--qa-style-input", type=Path, default=DATA_DIR / "chunk_qa_style_chunks.json")
    parser.add_argument("--hybrid-pool-size", type=int, default=10)
    parser.add_argument("--vector-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--bm25-k1", type=float, default=1.5)
    parser.add_argument("--bm25-b", type=float, default=0.75)
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--result-name")
    parser.add_argument("--include-doc4", action="store_true", help="기본 실험에서는 사용하지 않습니다.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
