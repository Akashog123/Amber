"""Print a labelled live meeting with Amber's replies, for review: [q] marks a request line."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

sc = {s["title"]: s for s in json.loads((Path(__file__).parent / "live.json").read_text(encoding="utf-8"))}
for mid in map(int, sys.argv[1:]):
    lines = iter(sc[f"Live meeting {mid}"]["lines"])
    n = 0
    for r in db.rows("SELECT speaker, text FROM utterances WHERE meeting_id=? ORDER BY id", mid):
        if r["speaker"] == "Amber":
            print(f"        AMBER: {r['text'][:90]}")
        else:
            n += 1
            x = next(lines)
            print(f"{n:3} {'[' + str(x['q'] % 1000) + ']' if x['q'] else '   '} {x['speaker']}: {x['text'][:110]}")
