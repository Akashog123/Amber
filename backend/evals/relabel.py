"""Apply hand review to evals/live.json: relabel.py <meeting> <line>=<request id or -> ...  (marks it reviewed)."""
import json
import sys
from pathlib import Path

path = Path(__file__).parent / "live.json"
saved = json.loads(path.read_text(encoding="utf-8"))
sc = next(s for s in saved if s["title"] == f"Live meeting {sys.argv[1]}")
mid = int(sys.argv[1])
for arg in sys.argv[2:]:
    n, q = arg.split("=")
    sc["lines"][int(n) - 1]["q"] = None if q == "-" else int(q) + mid * 1000
sc["reviewed"] = True
path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"meeting {mid}: {len({x['q'] for x in sc['lines'] if x['q']})} requests after review")
