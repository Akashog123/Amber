"""uv run python test_core.py — wake word, URL detection, and a full replay through the webhook."""
import os
import tempfile

os.environ["AMBER_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("RECALL_API_KEY", None)
os.environ["WEBHOOK_TOKEN"] = "t"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import replay  # noqa: E402

assert main.is_addressed("Agreed. Amber, what's the status?")
assert main.is_addressed("ember can you check")  # ASR mishearing
assert not main.is_addressed("the amberjack fish")
assert main.detect_platform("https://meet.google.com/abc-defg-hij") == "google_meet"
assert main.detect_platform("https://us02web.zoom.us/j/123") == "zoom"
assert main.detect_platform("http://meet.google.com/abc") is None
assert main.detect_platform("https://evil.com/meet.google.com") is None

c = TestClient(main.app)
assert c.post("/webhooks/recall?token=wrong", json={}).status_code == 401
mid = replay.run(c, speed=0)
m = c.get(f"/api/meetings/{mid}").json()
assert m["status"] == "done" and m["ended_at"], m["status"]
assert len(m["transcript"]) == sum(1 for s in replay.SCRIPT if s[1] == "say")
assert sum(u["addressed"] for u in m["transcript"]) == 2
assert {p["name"] for p in m["participants"]} == {"Akash", "Rahul", "Priya"}
assert all(p["left_at"] for p in m["participants"])
assert m["chat"][0]["sender"] == "Priya"
assert len(m["attendees"]) == 3
assert len(c.get("/api/records").json()) == 9
print("ok")
