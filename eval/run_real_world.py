"""Live baseline over the real-world NL → LaTeX corpus.

Sends every corpus input to a running TeXada API and judges the answer with
``real_world_lib.judge`` (empty / text-only / KaTeX / prose / forbid / anchor).
No verdict about model quality beyond this corpus is implied.

Usage:
    python eval/run_real_world.py --base-url http://127.0.0.1:18732
    python eval/run_real_world.py --category no-solving --limit 3
    python eval/run_real_world.py --dry-run        # judge the references only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from real_world_lib import CATEGORIES, judge, load_real_world_set

REPO = Path(__file__).resolve().parents[1]
ENDPOINT = {
    "completion": "/api/complete",
    "named-formula": "/api/convert",
    "lecture-sentence": "/api/convert",
    "common-mistake": "/api/convert",
    "no-solving": "/api/convert",
}


def post(base_url: str, path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def status(base_url: str, timeout: float) -> dict:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/status", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def run(args) -> dict:
    entries = load_real_world_set()
    if args.category:
        entries = [e for e in entries if e["category"] == args.category]
    if args.limit:
        entries = entries[: args.limit]

    rows = []
    info = {"status": "dry-run"}
    if not args.dry_run:
        try:
            info = status(args.base_url, args.timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"cannot reach {args.base_url}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    for index, entry in enumerate(entries, 1):
        if args.dry_run:
            latex, error, latency = entry["reference"], None, 0.0
        else:
            started = time.perf_counter()
            try:
                payload = post(
                    args.base_url,
                    ENDPOINT.get(entry["category"], "/api/convert"),
                    {"text": entry["input"], "render_mode": "katex"},
                    args.timeout,
                )
                latex, error = payload.get("latex", ""), None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                latex, error = "", f"{type(exc).__name__}: {exc}"
            latency = round((time.perf_counter() - started) * 1000, 1)
        ok, reasons = (False, [error]) if error else judge(entry, latex)
        rows.append(
            {
                "id": entry["id"],
                "category": entry["category"],
                "input": entry["input"],
                "output": latex,
                "ok": ok,
                "reasons": reasons,
                "latency_ms": latency,
            }
        )
        print(
            f"[{index:>3}/{len(entries)}] {'PASS' if ok else 'FAIL'} {entry['id']} "
            f"{entry['input'][:36]:<36} -> {(latex or '<empty>')[:48]}"
        )

    per_category = defaultdict(lambda: [0, 0])
    for row in rows:
        bucket = per_category[row["category"]]
        bucket[1] += 1
        bucket[0] += row["ok"]

    passed = sum(1 for r in rows if r["ok"])
    summary = {
        "schema_version": 1,
        "corpus": "eval/real_world_set.yaml",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dry_run": args.dry_run,
        "backend": {"status": info.get("status"), "model": info.get("model")},
        "claim": "Corpus-level transcription check only; not a general model benchmark",
        "total": len(rows),
        "passed": passed,
        "per_category": {
            k: {"passed": v[0], "total": v[1]} for k, v in sorted(per_category.items())
        },
        "rows": rows,
    }
    print(f"\n{passed}/{len(rows)} passed")
    for category, (ok, total) in sorted(per_category.items()):
        print(f"  {category:<17} {ok}/{total}")
    failures = Counter(r["id"] for r in rows if not r["ok"])
    if failures:
        print("\nfailed:", " ".join(sorted(failures)))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18732")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--category", choices=CATEGORIES, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="judge the authored references instead of calling the API",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    summary = run(args)
    if args.output:
        args.output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"report -> {args.output}")
    all_passed = summary["passed"] == summary["total"]
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
