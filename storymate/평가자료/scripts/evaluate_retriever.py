import argparse
import json
import math
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
STORYMATE_DIR = EVAL_DIR.parent
sys.path.insert(0, str(STORYMATE_DIR))

from utils import find_embedding_base_path, initialize_chroma_db, normalize_name  # noqa: E402

DATA_DIR = EVAL_DIR / "data"
RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_INPUT = DATA_DIR / "김첨지_검색기_평가셋_v1.xlsx"
DEFAULT_OUTPUT = RESULTS_DIR / "retriever_eval_results.jsonl"

DOC_DB_NAMES = {
    "doc1": "전문_chroma_db",
    "doc2": "인물평가_chroma_db",
    "doc3": "인물특성_chroma_db",
    "doc4": "예상질문_chroma_db",
}

SHEET_NAMES = {
    "Queries": "queries",
    "Qrels": "qrels",
    "Corpus": "corpus",
}

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "office_rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def read_shared_strings(xlsx: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in xlsx.namelist():
        return []

    root = ET.fromstring(xlsx.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.findall("main:si", NS):
        strings.append("".join(node.text or "" for node in item.findall(".//main:t", NS)))
    return strings


def cell_value(cell, shared_strings: list[str]) -> str:
    value = cell.find("main:v", NS)
    if value is None:
        inline = cell.find("main:is", NS)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.findall(".//main:t", NS))

    text = value.text or ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(text)]
    return text


def column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


def read_xlsx_tables(path: Path) -> dict[str, list[dict]]:
    with zipfile.ZipFile(path) as xlsx:
        shared_strings = read_shared_strings(xlsx)
        workbook = ET.fromstring(xlsx.read("xl/workbook.xml"))
        rels = ET.fromstring(xlsx.read("xl/_rels/workbook.xml.rels"))

        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("rel:Relationship", NS)
        }

        tables = {}
        for sheet in workbook.findall(".//main:sheet", NS):
            sheet_name = sheet.attrib["name"]
            table_name = SHEET_NAMES.get(sheet_name)
            if not table_name:
                continue

            rel_id = sheet.attrib[f"{{{NS['office_rel']}}}id"]
            target = rel_targets[rel_id]
            sheet_path = target.lstrip("/")
            if not sheet_path.startswith("xl/"):
                sheet_path = "xl/" + sheet_path
            sheet_root = ET.fromstring(xlsx.read(sheet_path))
            rows = []

            for row in sheet_root.findall(".//main:sheetData/main:row", NS):
                values = []
                for cell in row.findall("main:c", NS):
                    index = column_index(cell.attrib["r"])
                    while len(values) <= index:
                        values.append("")
                    values[index] = cell_value(cell, shared_strings)
                rows.append(values)

            if not rows:
                tables[table_name] = []
                continue

            headers = rows[0]
            records = []
            for row in rows[1:]:
                if not any(row):
                    continue
                records.append({
                    headers[index]: row[index] if index < len(row) else ""
                    for index in range(len(headers))
                })
            tables[table_name] = records

        return tables


def split_ids(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def load_evalset(path: Path) -> tuple[list[dict], dict[str, dict[str, int]], dict[str, dict]]:
    tables = read_xlsx_tables(path)
    queries = tables["queries"]
    corpus = {row["chunk_id"]: row for row in tables["corpus"]}
    qrels = defaultdict(dict)

    for row in tables["qrels"]:
        query_id = row["query_id"]
        chunk_id = row["chunk_id"]
        relevance = int(float(row["relevance"]))
        qrels[query_id][chunk_id] = relevance

    return queries, qrels, corpus


def find_named_embedding_base_path(book_title: str, character_name: str, embedding_dir_name: str) -> Path:
    normalized_character_name = normalize_name(character_name)
    candidate_paths = [
        STORYMATE_DIR / book_title / character_name / "data" / embedding_dir_name,
        STORYMATE_DIR / book_title / normalized_character_name / "data" / embedding_dir_name,
        STORYMATE_DIR / book_title / "data" / embedding_dir_name,
    ]

    for path in candidate_paths:
        if path.is_dir():
            return path

    raise FileNotFoundError(f"임베딩 데이터 경로를 찾을 수 없습니다: {candidate_paths[0]}")


def build_databases(book_title: str, character_name: str, include_doc4: bool, embedding_dir_name: str | None = None):
    if embedding_dir_name:
        base_path = find_named_embedding_base_path(book_title, character_name, embedding_dir_name)
    else:
        base_path = Path(find_embedding_base_path(str(STORYMATE_DIR), book_title, character_name))
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


def best_matching_chunk_id(text: str, doc_id: str, corpus: dict[str, dict]) -> str | None:
    normalized_text = normalize_text(text)
    best_chunk_id = None
    best_score = 0

    for chunk_id, row in corpus.items():
        if row.get("doc_id") != doc_id:
            continue

        chunk_text = normalize_text(row.get("text", ""))
        if not chunk_text:
            continue

        if chunk_text in normalized_text or normalized_text in chunk_text:
            return chunk_id

        overlap = len(set(chunk_text) & set(normalized_text))
        denominator = max(len(set(chunk_text)), 1)
        score = overlap / denominator
        if score > best_score:
            best_score = score
            best_chunk_id = chunk_id

    if best_score < 0.35:
        return None
    return best_chunk_id


def document_chunk_id(doc, doc_id: str, corpus: dict[str, dict]) -> str | None:
    metadata = getattr(doc, "metadata", {}) or {}
    for key in ("chunk_id", "id"):
        if metadata.get(key):
            return metadata[key]
    return best_matching_chunk_id(getattr(doc, "page_content", ""), doc_id, corpus)


def retrieve(query: str, databases: dict, corpus: dict[str, dict], k: int, per_doc_k: int):
    candidates = []

    for doc_id, db in databases.items():
        try:
            results = db.similarity_search_with_relevance_scores(query, k=per_doc_k)
        except AttributeError:
            results = [(doc, None) for doc in db.similarity_search(query, k=per_doc_k)]

        for rank_in_doc, (doc, score) in enumerate(results, start=1):
            chunk_id = document_chunk_id(doc, doc_id, corpus)
            candidates.append({
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "score": score,
                "rank_in_doc": rank_in_doc,
                "text": getattr(doc, "page_content", ""),
                "metadata": getattr(doc, "metadata", {}),
            })

    candidates.sort(key=lambda item: item["score"] if item["score"] is not None else 0, reverse=True)

    deduped = []
    seen = set()
    for candidate in candidates:
        dedup_key = candidate["chunk_id"] or (
            candidate["doc_id"],
            normalize_text(candidate["text"])[:120],
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        deduped.append(candidate)
        if len(deduped) >= k:
            break

    return deduped


def dcg(relevances: list[int]) -> float:
    return sum((2 ** rel - 1) / math.log2(index + 2) for index, rel in enumerate(relevances))


def score_query(query: dict, qrels: dict[str, int], retrieved: list[dict], k_values: list[int]) -> dict:
    relevant_chunk_ids = {chunk_id for chunk_id, relevance in qrels.items() if relevance >= 2}
    primary_chunk_ids = {chunk_id for chunk_id, relevance in qrels.items() if relevance >= 3}
    retrieved_chunk_ids = [row["chunk_id"] for row in retrieved if row["chunk_id"]]

    metrics = {}
    for k in k_values:
        top_k = retrieved_chunk_ids[:k]
        metrics[f"recall@{k}"] = int(bool(primary_chunk_ids & set(top_k)))
        metrics[f"hit@{k}"] = int(bool(relevant_chunk_ids & set(top_k)))

    reciprocal_rank = 0
    for index, chunk_id in enumerate(retrieved_chunk_ids[:5], start=1):
        if chunk_id in primary_chunk_ids:
            reciprocal_rank = 1 / index
            break
    metrics["mrr@5"] = reciprocal_rank

    actual_relevances = [qrels.get(chunk_id, 0) for chunk_id in retrieved_chunk_ids[:5]]
    ideal_relevances = sorted(qrels.values(), reverse=True)[:5]
    ideal_dcg = dcg(ideal_relevances)
    metrics["ndcg@5"] = dcg(actual_relevances) / ideal_dcg if ideal_dcg else 0

    if str(query.get("requires_multi_chunk", "0")) == "1":
        metrics["complete_recall@5"] = int(primary_chunk_ids.issubset(set(retrieved_chunk_ids[:5])))
    else:
        metrics["complete_recall@5"] = None

    return metrics


def summarize(rows: list[dict], k_values: list[int]) -> dict:
    groups = defaultdict(list)
    groups["all"] = rows
    for row in rows:
        groups[row["category"]].append(row)

    summary = {}
    metric_names = [f"recall@{k}" for k in k_values]
    metric_names += [f"hit@{k}" for k in k_values]
    metric_names += ["mrr@5", "ndcg@5", "complete_recall@5"]

    for group_name, group_rows in groups.items():
        group_summary = {"count": len(group_rows)}
        for metric_name in metric_names:
            values = [
                row["metrics"][metric_name]
                for row in group_rows
                if row["metrics"].get(metric_name) is not None
            ]
            if values:
                group_summary[metric_name] = round(sum(values) / len(values), 4)
        summary[group_name] = group_summary

    return summary


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(args):
    queries, qrels, corpus = load_evalset(args.input)
    if args.limit:
        queries = queries[:args.limit]

    databases = build_databases(args.book_title, args.character_name, args.include_doc4, args.embedding_dir_name)
    rows = []

    for index, query in enumerate(queries, start=1):
        query_id = query["query_id"]
        print(f"[{index}/{len(queries)}] {query_id} {query['category']}")

        retrieved = retrieve(
            query=query["query"],
            databases=databases,
            corpus=corpus,
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

    write_jsonl(args.output, rows)
    write_json(args.summary_output, summarize(rows, args.k_values))
    print(f"상세 결과 저장: {args.output}")
    print(f"요약 결과 저장: {args.summary_output}")


def parse_args():
    parser = argparse.ArgumentParser(description="김첨지 검색기 평가 스크립트")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=RESULTS_DIR / "retriever_eval_summary.json")
    parser.add_argument("--book-title", default="운수좋은날")
    parser.add_argument("--character-name", default="김첨지")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--per-doc-k", type=int, default=5)
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-doc4", action="store_true", help="예상질문(doc4) Chroma DB도 검색 대상에 포함합니다.")
    parser.add_argument("--embedding-dir-name", help="기본 data/embedding 대신 사용할 Chroma 디렉토리 이름입니다.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
