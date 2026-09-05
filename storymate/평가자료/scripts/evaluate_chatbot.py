import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
STORYMATE_DIR = EVAL_DIR.parent
sys.path.insert(0, str(STORYMATE_DIR))

from chatbot_sql import ChatBot  # noqa: E402

DATA_DIR = EVAL_DIR / "data"
RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_INPUT = DATA_DIR / "김첨지_캐릭터챗봇_평가데이터_v1.jsonl"
DEFAULT_OUTPUT = RESULTS_DIR / "eval_results.jsonl"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_samples(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def check_generation(sample: dict, response: str) -> dict:
    rubric = sample.get("generation_rubric", {})
    style = rubric.get("style_requirements", {})
    length_range = style.get("acceptable_length_range", [80, 260])
    must_include = rubric.get("must_include", [])
    must_not_claim = rubric.get("must_not_claim", [])

    hidden_reasoning_terms = ["내부 사고", "Chain-of-Thought", "단계별 사고", "생각 과정"]
    meta_terms = ["시스템 프롬프트", "프롬프트", "AI 모델", "언어 모델", "챗봇으로서"]
    emoji_terms = ["😀", "😃", "😄", "😁", "😆", "😂", "🙂", "😊", "😭", "😢", "❤️", "👍", "🤖"]

    checks = {
        "length": len(response),
        "length_ok": length_range[0] <= len(response) <= length_range[1],
        "no_emoji_ok": not contains_any(response, emoji_terms),
        "no_hidden_reasoning_ok": not contains_any(response, hidden_reasoning_terms),
        "no_ai_or_prompt_meta_ok": not contains_any(response, meta_terms),
        "must_include_hits": [term for term in must_include if term in response],
        "must_not_claim_hits": [term for term in must_not_claim if term in response],
    }
    checks["must_include_ok"] = not must_include or bool(checks["must_include_hits"])
    checks["must_not_claim_ok"] = not checks["must_not_claim_hits"]
    checks["format_ok"] = (
        checks["length_ok"]
        and checks["no_emoji_ok"]
        and checks["no_hidden_reasoning_ok"]
        and checks["no_ai_or_prompt_meta_ok"]
    )
    return checks


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_summary(path: Path, rows: list[dict], args):
    category_counts = Counter(row["category"] for row in rows)
    category_errors = Counter(row["category"] for row in rows if row.get("error"))
    category_format = defaultdict(lambda: {"ok": 0, "total": 0})

    for row in rows:
        category = row["category"]
        category_format[category]["total"] += 1
        if row.get("checks", {}).get("format_ok"):
            category_format[category]["ok"] += 1

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "retrieval_mode": args.retrieval_mode,
        "book_title": args.book_title,
        "character_name": args.character_name,
        "total": len(rows),
        "category_counts": dict(category_counts),
        "category_errors": dict(category_errors),
        "format_compliance": {
            category: {
                "ok": values["ok"],
                "total": values["total"],
                "rate": round(values["ok"] / values["total"], 4) if values["total"] else 0,
            }
            for category, values in sorted(category_format.items())
        },
    }

    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run_evaluation(args):
    samples = list(load_samples(args.input))
    if args.start:
        samples = samples[args.start:]
    if args.limit:
        samples = samples[:args.limit]

    logger.info("평가 샘플 %s개 로드", len(samples))
    bot = ChatBot(
        book_title=args.book_title,
        character_name=args.character_name,
        retrieval_mode=args.retrieval_mode,
    )
    rows = []

    for index, sample in enumerate(samples, start=1):
        session_id = f"eval_{sample['id']}"
        logger.info("[%s/%s] %s - %s", index, len(samples), sample["id"], sample["category"])

        try:
            response = bot.get_answer(
                session_id=session_id,
                user_query=sample["query"],
                chat_history_override=sample.get("chat_history", []),
                save_history=args.save_history,
            )
            row = {
                "id": sample["id"],
                "category": sample["category"],
                "subcategory": sample.get("subcategory"),
                "difficulty": sample.get("difficulty"),
                "query": sample["query"],
                "response": response,
                "retrieval_mode": args.retrieval_mode,
                "checks": check_generation(sample, response),
                "rubric": sample.get("generation_rubric", {}),
                "retrieval": sample.get("retrieval", {}),
            }
        except Exception as exc:
            logger.exception("평가 실패: %s", sample["id"])
            row = {
                "id": sample["id"],
                "category": sample.get("category"),
                "query": sample.get("query"),
                "error": str(exc),
            }

        rows.append(row)

    write_jsonl(args.output, rows)
    write_summary(args.output.with_suffix(".summary.json"), rows, args)
    logger.info("평가 결과 저장: %s", args.output)
    logger.info("평가 요약 저장: %s", args.output.with_suffix(".summary.json"))


def parse_args():
    parser = argparse.ArgumentParser(description="김첨지 캐릭터 챗봇 평가 실행기")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--book-title", default="운수좋은날")
    parser.add_argument("--character-name", default="김첨지")
    parser.add_argument("--retrieval-mode", choices=["default", "final_rerank"], default="default")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--save-history", action="store_true", help="평가 대화를 MariaDB에 저장합니다.")
    return parser.parse_args()


if __name__ == "__main__":
    run_evaluation(parse_args())
