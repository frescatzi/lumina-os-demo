"""lumina: demo command line."""
import argparse
import json
import os
from pathlib import Path

from lumina import api, kb

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed"


def _db():
    path = os.environ.get("LUMINA_DB", str(ROOT / "data" / "lumina.db"))
    os.environ["LUMINA_DB"] = path
    return path


def _profile():
    return json.loads((SEED / "profile.json").read_text())


def main():
    p = argparse.ArgumentParser(prog="lumina", description="Lumina OS demo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run the scout on the synthetic feed, then query the knowledge base")
    s = sub.add_parser("search", help="search the knowledge base")
    s.add_argument("query")
    v = sub.add_parser("serve", help="start the ingest API that n8n calls")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8787)
    sub.add_parser("mcp", help="start the MCP server on stdio")
    args = p.parse_args()

    if args.cmd == "demo":
        db = kb.connect(_db())
        feed = json.loads((SEED / "feed.json").read_text())
        print("Scout run 1:", kb.triage(db, feed, _profile()))
        print("Scout run 2:", kb.triage(db, feed, _profile()), "(idempotent)")
        changed = [dict(feed[0], body=feed[0]["body"] + " Updated with a benchmark section.")]
        print("Source changed:", kb.triage(db, changed, _profile()))
        for q in ["agent orchestration", "SAP integration"]:
            print(f"\nsearch: {q!r}")
            for hit in kb.search(db, q, 3):
                print(f"  - {hit['title']}  [{hit['source']}]")
        print("\nstats:", kb.stats(db))
    elif args.cmd == "search":
        print(json.dumps(kb.search(kb.connect(_db()), args.query), indent=2))
    elif args.cmd == "serve":
        server = api.make_server(args.host, args.port, _db(), _profile())
        print(f"Ingest API on http://{args.host}:{args.port} (POST /ingest, GET /health)")
        server.serve_forever()
    elif args.cmd == "mcp":
        _db()
        from lumina import mcp_server

        mcp_server.mcp.run()


if __name__ == "__main__":
    main()
