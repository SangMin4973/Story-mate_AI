import argparse
import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
DATA_DIR = EVAL_DIR / "data"
sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_retriever import load_evalset, split_ids  # noqa: E402

DEFAULT_INPUT = DATA_DIR / "김첨지_검색기_평가셋_v1.xlsx"
DEFAULT_OUTPUT_DIR = DATA_DIR / "retriever_eval_v1"


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            csv_row = {}
            for field in fieldnames:
                value = row.get(field, "")
                if isinstance(value, list):
                    value = "|".join(value)
                csv_row[field] = value
            writer.writerow(csv_row)


def normalize_queries(queries: list[dict], qrels: dict[str, dict[str, int]]) -> list[dict]:
    normalized = []
    for row in queries:
        query_id = row["query_id"]
        normalized.append({
            "query_id": query_id,
            "category": row.get("category", ""),
            "subcategory": row.get("subcategory", ""),
            "difficulty": row.get("difficulty", ""),
            "lexical_overlap": row.get("lexical_overlap", ""),
            "answerable": row.get("answerable", ""),
            "requires_multi_chunk": row.get("requires_multi_chunk", ""),
            "query": row.get("query", ""),
            "primary_gold_chunk_ids": split_ids(row.get("primary_gold_chunk_ids")),
            "relevant_chunk_ids": split_ids(row.get("relevant_chunk_ids")),
            "hard_negative_chunk_ids": split_ids(row.get("hard_negative_chunk_ids")),
            "target_doc_ids": split_ids(row.get("target_doc_ids")),
            "qrels": qrels.get(query_id, {}),
            "note": row.get("note", ""),
        })
    return normalized


def normalize_corpus(corpus: dict[str, dict]) -> list[dict]:
    return [
        {
            "chunk_id": chunk_id,
            "doc_id": row.get("doc_id", ""),
            "source_file": row.get("source_file", ""),
            "authority": row.get("authority", ""),
            "chunk_type": row.get("chunk_type", ""),
            "source_lines": row.get("source_lines", ""),
            "text": row.get("text", ""),
        }
        for chunk_id, row in sorted(corpus.items())
    ]


def validate_dataset(queries: list[dict], corpus_rows: list[dict]) -> dict:
    corpus_ids = {row["chunk_id"] for row in corpus_rows}
    missing_refs = []
    category_counts = {}

    for row in queries:
        category = row["category"]
        category_counts[category] = category_counts.get(category, 0) + 1

        referenced_ids = set(row["primary_gold_chunk_ids"])
        referenced_ids.update(row["relevant_chunk_ids"])
        referenced_ids.update(row["hard_negative_chunk_ids"])
        referenced_ids.update(row["qrels"].keys())

        for chunk_id in sorted(referenced_ids):
            if chunk_id not in corpus_ids:
                missing_refs.append({
                    "query_id": row["query_id"],
                    "chunk_id": chunk_id,
                })

    return {
        "query_count": len(queries),
        "corpus_count": len(corpus_rows),
        "category_counts": category_counts,
        "missing_reference_count": len(missing_refs),
        "missing_references": missing_refs[:50],
    }


def run(args):
    queries, qrels, corpus = load_evalset(args.input)
    normalized_queries = normalize_queries(queries, qrels)
    normalized_corpus = normalize_corpus(corpus)
    manifest = validate_dataset(normalized_queries, normalized_corpus)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "queries.jsonl", normalized_queries)
    write_jsonl(args.output_dir / "corpus.jsonl", normalized_corpus)
    write_jsonl(
        args.output_dir / "qrels.jsonl",
        [
            {"query_id": query_id, "chunk_id": chunk_id, "relevance": relevance}
            for query_id, chunks in sorted(qrels.items())
            for chunk_id, relevance in sorted(chunks.items())
        ],
    )
    write_csv(
        args.output_dir / "queries.csv",
        normalized_queries,
        [
            "query_id",
            "category",
            "subcategory",
            "difficulty",
            "lexical_overlap",
            "answerable",
            "requires_multi_chunk",
            "query",
            "primary_gold_chunk_ids",
            "relevant_chunk_ids",
            "hard_negative_chunk_ids",
            "target_doc_ids",
            "note",
        ],
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"queries: {manifest['query_count']}")
    print(f"corpus: {manifest['corpus_count']}")
    print(f"missing references: {manifest['missing_reference_count']}")
    print(f"output: {args.output_dir}")


def parse_args():
    parser = argparse.ArgumentParser(description="검색기 평가셋 정규화 스크립트")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
