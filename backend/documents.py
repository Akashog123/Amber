"""Text from a pre-meeting document (PDF, DOCX, TXT) so Amber joins already knowing it."""
import base64
import io
import re
import zipfile

from pypdf import PdfReader

MAX_BYTES = 10 * 1024 * 1024  # same limit as the dashboard
MAX_CHARS = 20_000  # keeps the answer prompt fast; ~5k tokens


def extract_text(name: str, b64: str) -> str:
    data = base64.b64decode(b64, validate=True)
    if len(data) > MAX_BYTES:
        raise ValueError("Document is larger than 10 MB.")
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    elif ext == "docx":  # a zip of XML: paragraphs are <w:p>, text runs are <w:t>
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))
    elif ext in ("txt", "md", "csv"):
        text = data.decode("utf-8", "ignore")
    else:
        raise ValueError("Supported documents: PDF, DOCX or TXT (old .doc files: save as .docx).")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_CHARS]


if __name__ == "__main__":
    sample = base64.b64encode(b"Pump vendor: FlowServe.\n\n\n\nBudget 4.2L").decode()
    assert extract_text("notes.txt", sample) == "Pump vendor: FlowServe.\n\nBudget 4.2L"
    try:
        extract_text("old.doc", sample)
        raise AssertionError("doc should be rejected")
    except ValueError:
        pass
    print("ok")
