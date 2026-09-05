import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EVAL_DIR = SCRIPT_DIR.parent
RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_BASELINE = RESULTS_DIR / "eval_results.jsonl"
DEFAULT_CANDIDATE = RESULTS_DIR / "eval_results_final_rerank.jsonl"
DEFAULT_OUTPUT = RESULTS_DIR / "eval_comparison_final_rerank.json"

CHECK_KEYS = [
    "format_ok",
    "length_ok",
    "no_emoji_ok",
    "no_hidden_reasoning_ok",
    "no_ai_or_prompt_meta_ok",
    "must_include_ok",
    "must_not_claim_ok",
]


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def rate(ok: int, total: int) -> float:
    return round(ok / total, 4) if total else 0


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    error_count = sum(1 for row in rows if row.get("error"))
    categories = Counter(row.get("category") for row in rows)
    check_counts = {key: 0 for key in CHECK_KEYS}
    category_checks = defaultdict(lambda: {key: {"ok": 0, "total": 0} for key in CHECK_KEYS})

    for row in rows:
        checks = row.get("checks", {})
        category = row.get("category")
        for key in CHECK_KEYS:
            if key in checks:
                check_counts[key] += int(bool(checks[key]))
                category_checks[category][key]["ok"] += int(bool(checks[key]))
                category_checks[category][key]["total"] += 1

    return {
        "total": total,
        "error_count": error_count,
        "category_counts": dict(categories),
        "checks": {
            key: {
                "ok": check_counts[key],
                "total": total,
                "rate": rate(check_counts[key], total),
            }
            for key in CHECK_KEYS
        },
        "category_checks": {
            category: {
                key: {
                    "ok": values[key]["ok"],
                    "total": values[key]["total"],
                    "rate": rate(values[key]["ok"], values[key]["total"]),
                }
                for key in CHECK_KEYS
            }
            for category, values in sorted(category_checks.items())
        },
    }


def diff_summary(baseline: dict, candidate: dict) -> dict:
    check_diff = {}
    for key in CHECK_KEYS:
        baseline_rate = baseline["checks"][key]["rate"]
        candidate_rate = candidate["checks"][key]["rate"]
        check_diff[key] = {
            "baseline": baseline_rate,
            "candidate": candidate_rate,
            "diff": round(candidate_rate - baseline_rate, 4),
        }

    categories = set(baseline["category_checks"]) | set(candidate["category_checks"])
    category_diff = {}
    for category in sorted(categories):
        category_diff[category] = {}
        for key in CHECK_KEYS:
            baseline_rate = baseline["category_checks"].get(category, {}).get(key, {}).get("rate", 0)
            candidate_rate = candidate["category_checks"].get(category, {}).get(key, {}).get("rate", 0)
            category_diff[category][key] = {
                "baseline": baseline_rate,
                "candidate": candidate_rate,
                "diff": round(candidate_rate - baseline_rate, 4),
            }

    return {
        "checks": check_diff,
        "category_checks": category_diff,
    }


def run(args):
    baseline_rows = read_jsonl(args.baseline)
    candidate_rows = read_jsonl(args.candidate)
    baseline_summary = summarize(baseline_rows)
    candidate_summary = summarize(candidate_rows)
    comparison = {
        "baseline_path": str(args.baseline),
        "candidate_path": str(args.candidate),
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "diff": diff_summary(baseline_summary, candidate_summary),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"비교 결과 저장: {args.output}")
    print("주요 차이:")
    for key in CHECK_KEYS:
        item = comparison["diff"]["checks"][key]
        print(f"- {key}: {item['baseline']} -> {item['candidate']} ({item['diff']:+.4f})")


def parse_args():
    parser = argparse.ArgumentParser(description="챗봇 평가 결과 비교")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
