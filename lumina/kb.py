"""Self-updating knowledge base: score, ingest idempotently, search with BM25."""
import hashlib
import re
import sqlite3
from datetime import datetime, timezone

from lumina import router

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(id UNINDEXED, title, body);
"""


def connect(path):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def score(item, profile):
    """Share of profile keywords found in the item, from 0.0 to 1.0.

    ponytail: substring match ("sap" also hits "sapling"); swap for an LLM classify call when precision matters.
    """
    text = f"{item.get('title', '')} {item.get('body', '')}".lower()
    keywords = profile["keywords"]
    return sum(k.lower() in text for k in keywords) / len(keywords) if keywords else 0.0


def validate(item):
    """Normalize one untrusted item or raise ValueError."""
    if not isinstance(item, dict):
        raise ValueError("item must be an object")
    clean = {k: item.get(k) or "" for k in ("url", "title", "body", "source")}
    if not all(isinstance(v, str) for v in clean.values()):
        raise ValueError("url, title, body and source must be strings")
    if not clean["url"]:
        raise ValueError("item needs a url")
    clean["source"] = clean["source"] or "manual"
    return clean


def _upsert(db, item):
    item = validate(item)
    doc_id, digest = _sha(item["url"])[:16], _sha(item["title"] + "\n" + item["body"])
    row = db.execute("SELECT content_hash FROM docs WHERE id = ?", (doc_id,)).fetchone()
    if row and row["content_hash"] == digest:
        return "unchanged"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = router.complete("summarize", item["body"])
    db.execute(
        "INSERT OR REPLACE INTO docs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc_id, item["url"], item["title"], summary, item["source"], digest, now),
    )
    # ponytail: id is UNINDEXED in FTS5, so this delete scans the table; use an external-content table past ~100k docs.
    db.execute("DELETE FROM docs_fts WHERE id = ?", (doc_id,))
    db.execute("INSERT INTO docs_fts VALUES (?, ?, ?)", (doc_id, item["title"], item["body"]))
    return "updated" if row else "inserted"


def ingest(db, item):
    """Insert, update or skip one item. Identity is the URL, freshness is the content hash."""
    with db:
        return _upsert(db, item)


def triage(db, items, profile):
    """The scout step: keep items above the profile threshold, ingest them, report counts.

    The batch is atomic: every item is validated first, and any error rolls back all writes.
    """
    items = [validate(i) for i in items]
    report = {"inserted": 0, "updated": 0, "unchanged": 0, "rejected": 0}
    with db:
        for item in items:
            if score(item, profile) < profile.get("threshold", 0.5):
                report["rejected"] += 1
            else:
                report[_upsert(db, item)] += 1
    return report


def search(db, query, limit=5):
    # Quote every term so user input is never parsed as FTS5 syntax.
    terms = re.findall(r"\w+", query)
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = db.execute(
        """SELECT d.id, d.title, d.url, d.summary, d.source FROM docs_fts f
           JOIN docs d ON d.id = f.id WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?""",
        (match, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get(db, doc_id):
    row = db.execute(
        "SELECT d.*, f.body FROM docs d JOIN docs_fts f ON f.id = d.id WHERE d.id = ?", (doc_id,)
    ).fetchone()
    return dict(row) if row else None


def stats(db):
    n, last = db.execute("SELECT COUNT(*), MAX(updated_at) FROM docs").fetchone()
    return {"documents": n, "last_update": last}
