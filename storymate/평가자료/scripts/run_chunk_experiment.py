import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
STORYMATE_DIR = EVAL_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(STORYMATE_DIR))

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_openai import OpenAIEmbeddings  # noqa: E402

from evaluate_retriever import (  # noqa: E402
    DOC_DB_NAMES,
    dcg,
    load_evalset,
    normalize_text,
    split_ids,
    summarize,
    write_json,
    write_jsonl,
)
from utils import find_embedding_base_path, initialize_chroma_db  # noqa: E402

DATA_DIR = EVAL_DIR / "data"
RESULT_DIR = EVAL_DIR / "result" / "chunk_experiments"
DEFAULT_INPUT = DATA_DIR / "김첨지_검색기_평가셋_v1.xlsx"
DEFAULT_QA_STYLE_INPUT = DATA_DIR / "chunk_qa_style_chunks.json"

SUPPORTED_EXPERIMENTS = {
    "chunk_larger",
    "chunk_larger_overlap",
    "chunk_larger_qa_added",
    "chunk_overlap",
    "chunk_qa_style",
    "doc1_context",
}


def ensure_safe_child_path(parent: Path, child: Path):
    parent = parent.resolve()
    child = child.resolve()
    if parent != child and parent not in child.parents:
        raise ValueError(f"허용되지 않은 경로입니다: {child}")


def group_corpus_by_doc(corpus: dict[str, dict], include_doc4: bool) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for chunk_id, row in corpus.items():
        doc_id = row.get("doc_id")
        if doc_id == "doc4" and not include_doc4:
            continue
        if doc_id not in DOC_DB_NAMES:
            continue

        grouped[doc_id].append({
            "chunk_id": chunk_id,
            **row,
        })

    for rows in grouped.values():
        rows.sort(key=lambda item: item["chunk_id"])
    return grouped


def merge_rows(doc_id: str, rows: list[dict], experiment: str, start: int, end: int) -> dict:
    selected = rows[start:end]
    source_chunk_ids = [row["chunk_id"] for row in selected]
    text = "\n".join(row.get("text", "") for row in selected if row.get("text"))
    first = selected[0]

    return {
        "chunk_id": f"{doc_id}_{experiment}_{start + 1:02d}_{end:02d}",
        "doc_id": doc_id,
        "text": text,
        "source_chunk_ids": source_chunk_ids,
        "source_file": first.get("source_file", ""),
        "authority": first.get("authority", ""),
        "chunk_type": first.get("chunk_type", ""),
        "source_lines": "|".join(row.get("source_lines", "") for row in selected if row.get("source_lines")),
    }


def passthrough_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        output.append({
            "chunk_id": row["chunk_id"],
            "doc_id": row.get("doc_id", ""),
            "text": row.get("text", ""),
            "source_chunk_ids": [row["chunk_id"]],
            "source_file": row.get("source_file", ""),
            "authority": row.get("authority", ""),
            "chunk_type": row.get("chunk_type", ""),
            "source_lines": row.get("source_lines", ""),
        })
    return output


def make_larger_chunks(grouped: dict[str, list[dict]], group_size: int) -> dict[str, list[dict]]:
    transformed = {}
    for doc_id, rows in grouped.items():
        if doc_id in {"doc2", "doc3"}:
            transformed[doc_id] = [
                merge_rows(doc_id, rows, "larger", start, min(start + group_size, len(rows)))
                for start in range(0, len(rows), group_size)
            ]
        else:
            transformed[doc_id] = passthrough_rows(rows)
    return transformed


def make_overlap_chunks(grouped: dict[str, list[dict]], window_size: int, stride: int) -> dict[str, list[dict]]:
    transformed = {}
    for doc_id, rows in grouped.items():
        if doc_id in {"doc2", "doc3"}:
            doc_chunks = []
            for start in range(0, len(rows), stride):
                end = min(start + window_size, len(rows))
                if end <= start:
                    continue
                doc_chunks.append(merge_rows(doc_id, rows, "overlap", start, end))
                if end == len(rows):
                    break
            transformed[doc_id] = doc_chunks
        else:
            transformed[doc_id] = passthrough_rows(rows)
    return transformed


def make_larger_overlap_chunks(grouped: dict[str, list[dict]], group_size: int) -> dict[str, list[dict]]:
    transformed = {}
    for doc_id, rows in grouped.items():
        if doc_id == "doc2":
            transformed[doc_id] = [
                merge_rows(doc_id, rows, "larger", start, min(start + group_size, len(rows)))
                for start in range(0, len(rows), group_size)
            ]
        elif doc_id == "doc3":
            doc_chunks = []
            for start in range(0, len(rows)):
                end = min(start + group_size, len(rows))
                if end <= start:
                    continue
                doc_chunks.append(merge_rows(doc_id, rows, "larger_overlap", start, end))
                if end == len(rows):
                    break
            transformed[doc_id] = doc_chunks
        else:
            transformed[doc_id] = passthrough_rows(rows)
    return transformed


def load_qa_style_chunks(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    required_keys = {"chunk_id", "doc_id", "source_chunk_ids", "text"}

    for index, row in enumerate(rows, start=1):
        missing_keys = required_keys - set(row)
        if missing_keys:
            raise ValueError(f"QA-style 청크 {index}번에 필수 키가 없습니다: {', '.join(sorted(missing_keys))}")
        if row["doc_id"] not in {"doc2", "doc3"}:
            raise ValueError(f"QA-style 청크는 doc2/doc3만 지원합니다: {row['chunk_id']}")
        if not isinstance(row["source_chunk_ids"], list) or not row["source_chunk_ids"]:
            raise ValueError(f"source_chunk_ids는 비어 있지 않은 list여야 합니다: {row['chunk_id']}")

    return rows


def make_qa_style_chunks(grouped: dict[str, list[dict]], qa_style_input: Path) -> dict[str, list[dict]]:
    transformed = {}
    source_lookup = {
        row["chunk_id"]: row
        for rows in grouped.values()
        for row in rows
    }

    for doc_id, rows in grouped.items():
        if doc_id not in {"doc2", "doc3"}:
            transformed[doc_id] = passthrough_rows(rows)

    for row in load_qa_style_chunks(qa_style_input):
        missing_source_ids = [
            chunk_id
            for chunk_id in row["source_chunk_ids"]
            if chunk_id not in source_lookup
        ]
        if missing_source_ids:
            raise ValueError(f"QA-style 청크의 원본 청크를 찾을 수 없습니다: {row['chunk_id']} -> {missing_source_ids}")

        source_rows = [source_lookup[chunk_id] for chunk_id in row["source_chunk_ids"]]
        first = source_rows[0]
        transformed.setdefault(row["doc_id"], []).append({
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "text": row["text"],
            "source_chunk_ids": row["source_chunk_ids"],
            "source_file": row.get("source_file", first.get("source_file", "")),
            "authority": row.get("authority", first.get("authority", "")),
            "chunk_type": row.get("chunk_type", "qa_style"),
            "source_lines": row.get(
                "source_lines",
                "|".join(source.get("source_lines", "") for source in source_rows if source.get("source_lines")),
            ),
        })

    for doc_id in ("doc2", "doc3"):
        transformed.setdefault(doc_id, [])
        transformed[doc_id].sort(key=lambda item: item["chunk_id"])

    return transformed


def make_larger_qa_added_chunks(
    grouped: dict[str, list[dict]],
    group_size: int,
    qa_style_input: Path,
) -> dict[str, list[dict]]:
    transformed = make_larger_chunks(grouped, group_size)
    source_lookup = {
        row["chunk_id"]: row
        for rows in grouped.values()
        for row in rows
    }

    for row in load_qa_style_chunks(qa_style_input):
        missing_source_ids = [
            chunk_id
            for chunk_id in row["source_chunk_ids"]
            if chunk_id not in source_lookup
        ]
        if missing_source_ids:
            raise ValueError(f"QA-style 청크의 원본 청크를 찾을 수 없습니다: {row['chunk_id']} -> {missing_source_ids}")

        source_rows = [source_lookup[chunk_id] for chunk_id in row["source_chunk_ids"]]
        first = source_rows[0]
        transformed.setdefault(row["doc_id"], []).append({
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "text": row["text"],
            "source_chunk_ids": row["source_chunk_ids"],
            "source_file": row.get("source_file", first.get("source_file", "")),
            "authority": row.get("authority", first.get("authority", "")),
            "chunk_type": row.get("chunk_type", "qa_style_added"),
            "source_lines": row.get(
                "source_lines",
                "|".join(source.get("source_lines", "") for source in source_rows if source.get("source_lines")),
            ),
        })

    for doc_id in ("doc2", "doc3"):
        transformed.setdefault(doc_id, [])
        transformed[doc_id].sort(key=lambda item: item["chunk_id"])

    return transformed


def make_doc1_context_chunks(grouped: dict[str, list[dict]], window_size: int, stride: int) -> dict[str, list[dict]]:
    transformed = {}
    for doc_id, rows in grouped.items():
        if doc_id == "doc1":
            doc_chunks = []
            for start in range(0, len(rows), stride):
                end = min(start + window_size, len(rows))
                if end <= start:
                    continue
                doc_chunks.append(merge_rows(doc_id, rows, "context", start, end))
                if end == len(rows):
                    break
            transformed[doc_id] = doc_chunks
        else:
            transformed[doc_id] = passthrough_rows(rows)
    return transformed


def transform_corpus(corpus: dict[str, dict], args) -> dict[str, list[dict]]:
    grouped = group_corpus_by_doc(corpus, args.include_doc4)

    if args.experiment == "chunk_larger":
        return make_larger_chunks(grouped, args.group_size)
    if args.experiment == "chunk_larger_overlap":
        return make_larger_overlap_chunks(grouped, args.group_size)
    if args.experiment == "chunk_larger_qa_added":
        return make_larger_qa_added_chunks(grouped, args.group_size, args.qa_style_input)
    if args.experiment == "chunk_overlap":
        return make_overlap_chunks(grouped, args.window_size, args.stride)
    if args.experiment == "chunk_qa_style":
        return make_qa_style_chunks(grouped, args.qa_style_input)
    if args.experiment == "doc1_context":
        return make_doc1_context_chunks(grouped, args.window_size, args.stride)

    raise ValueError(f"지원하지 않는 실험입니다: {args.experiment}")


def make_documents(rows: list[dict]) -> tuple[list[Document], list[str]]:
    documents = []
    ids = []
    for row in rows:
        chunk_id = row["chunk_id"]
        source_chunk_ids = row["source_chunk_ids"]
        ids.append(chunk_id)
        documents.append(
            Document(
                page_content=row["text"],
                metadata={
                    "chunk_id": chunk_id,
                    "doc_id": row.get("doc_id", ""),
                    "source_chunk_ids": "|".join(source_chunk_ids),
                    "source_file": row.get("source_file", ""),
                    "authority": row.get("authority", ""),
                    "chunk_type": row.get("chunk_type", ""),
                    "source_lines": row.get("source_lines", ""),
                },
            )
        )
    return documents, ids


def rebuild_chroma(transformed: dict[str, list[dict]], output_base_path: Path, apply: bool):
    plan = []
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002") if apply else None

    if apply and output_base_path.exists():
        ensure_safe_child_path(STORYMATE_DIR, output_base_path)
        shutil.rmtree(output_base_path)

    for doc_id, db_name in DOC_DB_NAMES.items():
        rows = transformed.get(doc_id, [])
        if not rows:
            continue

        db_path = output_base_path / db_name
        plan.append({
            "doc_id": doc_id,
            "db_name": db_name,
            "db_path": str(db_path),
            "chunk_count": len(rows),
        })

        if apply:
            documents, ids = make_documents(rows)
            Chroma.from_documents(
                documents=documents,
                embedding=embeddings,
                ids=ids,
                persist_directory=str(db_path),
            )

    return plan


def build_databases(base_path: Path, include_doc4: bool) -> dict:
    databases = {}
    for doc_id, db_name in DOC_DB_NAMES.items():
        if doc_id == "doc4" and not include_doc4:
            continue

        db_path = base_path / db_name
        if db_path.is_dir():
            databases[doc_id] = initialize_chroma_db(str(db_path))

    if not databases:
        raise FileNotFoundError(f"사용 가능한 Chroma DB를 찾을 수 없습니다: {base_path}")
    return databases


def document_source_chunk_ids(doc, doc_id: str, transformed: dict[str, list[dict]]) -> list[str]:
    metadata = getattr(doc, "metadata", {}) or {}
    source_chunk_ids = split_ids(metadata.get("source_chunk_ids", ""))
    if source_chunk_ids:
        return source_chunk_ids

    chunk_id = metadata.get("chunk_id")
    if chunk_id:
        return [chunk_id]

    normalized_text = normalize_text(getattr(doc, "page_content", ""))
    for row in transformed.get(doc_id, []):
        if normalize_text(row.get("text", "")) == normalized_text:
            return row["source_chunk_ids"]
    return []


def retrieve(query: str, databases: dict, transformed: dict[str, list[dict]], k: int, per_doc_k: int):
    candidates = []
    for doc_id, db in databases.items():
        try:
            results = db.similarity_search_with_relevance_scores(query, k=per_doc_k)
        except AttributeError:
            results = [(doc, None) for doc in db.similarity_search(query, k=per_doc_k)]

        for rank_in_doc, (doc, score) in enumerate(results, start=1):
            metadata = getattr(doc, "metadata", {}) or {}
            source_chunk_ids = document_source_chunk_ids(doc, doc_id, transformed)
            candidates.append({
                "doc_id": doc_id,
                "chunk_id": metadata.get("chunk_id"),
                "source_chunk_ids": source_chunk_ids,
                "score": score,
                "rank_in_doc": rank_in_doc,
                "text": getattr(doc, "page_content", ""),
                "metadata": metadata,
            })

    candidates.sort(key=lambda item: item["score"] if item["score"] is not None else 0, reverse=True)

    deduped = []
    seen = set()
    for candidate in candidates:
        dedup_key = candidate["chunk_id"] or (
            candidate["doc_id"],
            tuple(candidate["source_chunk_ids"]),
            normalize_text(candidate["text"])[:120],
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        deduped.append(candidate)
        if len(deduped) >= k:
            break
    return deduped


def score_query(query: dict, qrels: dict[str, int], retrieved: list[dict], k_values: list[int]) -> dict:
    relevant_chunk_ids = {chunk_id for chunk_id, relevance in qrels.items() if relevance >= 2}
    primary_chunk_ids = {chunk_id for chunk_id, relevance in qrels.items() if relevance >= 3}
    retrieved_sources = [set(row["source_chunk_ids"]) for row in retrieved]

    metrics = {}
    for k in k_values:
        top_k_sources = set().union(*retrieved_sources[:k]) if retrieved_sources[:k] else set()
        metrics[f"recall@{k}"] = int(bool(primary_chunk_ids & top_k_sources))
        metrics[f"hit@{k}"] = int(bool(relevant_chunk_ids & top_k_sources))

    reciprocal_rank = 0
    for index, source_chunk_ids in enumerate(retrieved_sources[:5], start=1):
        if primary_chunk_ids & source_chunk_ids:
            reciprocal_rank = 1 / index
            break
    metrics["mrr@5"] = reciprocal_rank

    credited_chunk_ids = set()
    actual_relevances = []
    for source_chunk_ids in retrieved_sources[:5]:
        uncredited_relevances = [
            qrels.get(chunk_id, 0)
            for chunk_id in source_chunk_ids
            if chunk_id not in credited_chunk_ids
        ]
        actual_relevances.append(max(uncredited_relevances or [0]))
        credited_chunk_ids.update(source_chunk_ids)
    ideal_relevances = sorted(qrels.values(), reverse=True)[:5]
    ideal_dcg = dcg(ideal_relevances)
    metrics["ndcg@5"] = dcg(actual_relevances) / ideal_dcg if ideal_dcg else 0

    if str(query.get("requires_multi_chunk", "0")) == "1":
        top_5_sources = set().union(*retrieved_sources[:5]) if retrieved_sources[:5] else set()
        metrics["complete_recall@5"] = int(primary_chunk_ids.issubset(top_5_sources))
    else:
        metrics["complete_recall@5"] = None
    return metrics


def write_manifest(path: Path, args, plan: list[dict]):
    manifest = {
        "experiment": args.experiment,
        "input": str(args.input),
        "include_doc4": args.include_doc4,
        "k": args.k,
        "per_doc_k": args.per_doc_k,
        "k_values": args.k_values,
        "group_size": args.group_size,
        "window_size": args.window_size,
        "stride": args.stride,
        "qa_style_input": str(args.qa_style_input),
        "plan": plan,
    }
    write_json(path, manifest)


def run(args):
    if args.experiment not in SUPPORTED_EXPERIMENTS:
        raise ValueError(f"--experiment은 다음 중 하나여야 합니다: {', '.join(sorted(SUPPORTED_EXPERIMENTS))}")
    if args.result_name and any(separator in args.result_name for separator in ("/", "\\")):
        raise ValueError("--result-name에는 폴더 구분자를 포함할 수 없습니다.")

    queries, qrels, corpus = load_evalset(args.input)
    if args.limit:
        queries = queries[:args.limit]

    current_embedding_path = Path(
        find_embedding_base_path(str(STORYMATE_DIR), args.book_title, args.character_name)
    )
    output_base_path = current_embedding_path.parent / "chunk_experiments" / args.experiment
    experiment_result_dir = RESULT_DIR / (args.result_name or args.experiment)

    transformed = transform_corpus(corpus, args)
    plan = rebuild_chroma(transformed, output_base_path, apply=args.build)
    write_manifest(experiment_result_dir / "manifest.json", args, plan)

    print(f"experiment: {args.experiment}")
    print(f"chroma output: {output_base_path}")
    print(f"result dir: {experiment_result_dir}")
    print(f"build: {args.build}")
    for item in plan:
        print(f"- {item['doc_id']} -> {item['db_path']} ({item['chunk_count']} chunks)")

    if not args.evaluate:
        print("평가까지 진행하려면 --evaluate를 붙이세요.")
        return

    databases = build_databases(output_base_path, args.include_doc4)
    rows = []
    for index, query in enumerate(queries, start=1):
        query_id = query["query_id"]
        print(f"[{index}/{len(queries)}] {query_id} {query['category']}")
        retrieved = retrieve(
            query=query["query"],
            databases=databases,
            transformed=transformed,
            k=args.k,
            per_doc_k=args.per_doc_k,
        )
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

    detail_path = experiment_result_dir / "retriever_eval.jsonl"
    summary_path = experiment_result_dir / "retriever_eval_summary.json"
    write_jsonl(detail_path, rows)
    write_json(summary_path, summarize(rows, args.k_values))
    print(f"상세 결과 저장: {detail_path}")
    print(f"요약 결과 저장: {summary_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="청크 구성 실험용 Chroma 재생성 및 검색기 평가")
    parser.add_argument("--experiment", required=True, choices=sorted(SUPPORTED_EXPERIMENTS))
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
    parser.add_argument("--qa-style-input", type=Path, default=DEFAULT_QA_STYLE_INPUT)
    parser.add_argument("--result-name", help="결과를 저장할 실험 결과 디렉토리 이름입니다.")
    parser.add_argument("--include-doc4", action="store_true", help="기본 실험에서는 사용하지 않습니다.")
    parser.add_argument("--build", action="store_true", help="실험용 Chroma DB를 생성합니다.")
    parser.add_argument("--evaluate", action="store_true", help="생성된 실험용 Chroma DB를 평가합니다.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
