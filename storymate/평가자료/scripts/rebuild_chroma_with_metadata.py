import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
STORYMATE_DIR = EVAL_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(STORYMATE_DIR))

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_openai import OpenAIEmbeddings  # noqa: E402

from evaluate_retriever import DOC_DB_NAMES, load_evalset  # noqa: E402
from utils import find_embedding_base_path  # noqa: E402

DATA_DIR = EVAL_DIR / "data"
DEFAULT_INPUT = DATA_DIR / "김첨지_검색기_평가셋_v1.xlsx"


def ensure_safe_child_path(parent: Path, child: Path):
    parent = parent.resolve()
    child = child.resolve()
    if parent != child and parent not in child.parents:
        raise ValueError(f"허용되지 않은 경로입니다: {child}")


def group_corpus_by_doc(corpus: dict[str, dict]) -> dict[str, list[dict]]:
    grouped = {}
    for chunk_id, row in corpus.items():
        doc_id = row.get("doc_id")
        if doc_id not in DOC_DB_NAMES:
            continue

        grouped.setdefault(doc_id, []).append({
            "chunk_id": chunk_id,
            **row,
        })

    for rows in grouped.values():
        rows.sort(key=lambda item: item["chunk_id"])
    return grouped


def make_documents(rows: list[dict]) -> tuple[list[Document], list[str]]:
    documents = []
    ids = []

    for row in rows:
        chunk_id = row["chunk_id"]
        ids.append(chunk_id)
        documents.append(
            Document(
                page_content=row.get("text", ""),
                metadata={
                    "chunk_id": chunk_id,
                    "doc_id": row.get("doc_id", ""),
                    "source_file": row.get("source_file", ""),
                    "authority": row.get("authority", ""),
                    "chunk_type": row.get("chunk_type", ""),
                    "source_lines": row.get("source_lines", ""),
                },
            )
        )

    return documents, ids


def remove_directory(path: Path):
    if path.exists():
        ensure_safe_child_path(STORYMATE_DIR, path)
        shutil.rmtree(path)


def backup_current_embedding(current_path: Path) -> Path | None:
    if not current_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = current_path.with_name(f"{current_path.name}_backup_{timestamp}")
    ensure_safe_child_path(current_path.parent, backup_path)
    shutil.move(str(current_path), str(backup_path))
    return backup_path


def rebuild_databases(corpus: dict[str, dict], output_base_path: Path, apply: bool):
    grouped = group_corpus_by_doc(corpus)
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002") if apply else None
    plan = []

    for doc_id, db_name in DOC_DB_NAMES.items():
        rows = grouped.get(doc_id, [])
        db_path = output_base_path / db_name
        plan.append({
            "doc_id": doc_id,
            "db_name": db_name,
            "db_path": str(db_path),
            "chunk_count": len(rows),
        })

        if not apply:
            continue

        remove_directory(db_path)
        documents, ids = make_documents(rows)
        if not documents:
            continue

        Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            ids=ids,
            persist_directory=str(db_path),
        )

    return plan


def run(args):
    _, _, corpus = load_evalset(args.input)
    current_embedding_path = Path(
        find_embedding_base_path(str(STORYMATE_DIR), args.book_title, args.character_name)
    )

    if args.replace_current:
        output_base_path = current_embedding_path
    else:
        output_base_path = current_embedding_path.with_name(args.output_dir_name)

    ensure_safe_child_path(STORYMATE_DIR, output_base_path)

    print(f"input: {args.input}")
    print(f"current embedding: {current_embedding_path}")
    print(f"output embedding: {output_base_path}")
    print(f"replace current: {args.replace_current}")
    print(f"apply: {args.apply}")

    if not args.apply:
        plan = rebuild_databases(corpus, output_base_path, apply=False)
        print("dry-run 결과:")
        for item in plan:
            print(f"- {item['doc_id']} -> {item['db_path']} ({item['chunk_count']} chunks)")
        print("실제 재생성하려면 --apply를 붙이세요.")
        return

    backup_path = None
    if args.replace_current:
        backup_path = backup_current_embedding(current_embedding_path)
    else:
        remove_directory(output_base_path)

    plan = rebuild_databases(corpus, output_base_path, apply=True)
    print("Chroma DB 재생성 완료:")
    for item in plan:
        print(f"- {item['doc_id']} -> {item['db_path']} ({item['chunk_count']} chunks)")
    if backup_path:
        print(f"기존 embedding 백업: {backup_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="평가셋 Corpus 기준 Chroma DB metadata 재생성")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--book-title", default="운수좋은날")
    parser.add_argument("--character-name", default="김첨지")
    parser.add_argument("--output-dir-name", default="embedding_metadata")
    parser.add_argument("--replace-current", action="store_true", help="기존 data/embedding을 백업하고 새 DB로 교체합니다.")
    parser.add_argument("--apply", action="store_true", help="실제 Chroma DB를 생성합니다. 없으면 dry-run만 수행합니다.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
