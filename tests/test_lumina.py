import asyncio
import http.client
import json
import os
import tempfile
import threading
import unittest
import unittest.mock
import urllib.request

from lumina import api, kb, router


class KnowledgeBaseTest(unittest.TestCase):
    def setUp(self):
        self.db = kb.connect(":memory:")
        self.addCleanup(self.db.close)

    def test_ingest_is_idempotent(self):
        item = {"title": "Agents", "body": "Multi-agent orchestration with n8n.", "url": "https://example.com/a"}
        self.assertEqual(kb.ingest(self.db, item), "inserted")
        self.assertEqual(kb.ingest(self.db, item), "unchanged")
        self.assertEqual(kb.stats(self.db)["documents"], 1)

    def test_changed_content_updates_in_place(self):
        item = {"title": "Agents", "body": "v1", "url": "https://example.com/a"}
        kb.ingest(self.db, item)
        self.assertEqual(kb.ingest(self.db, dict(item, body="v2 with retrieval")), "updated")
        self.assertEqual(kb.stats(self.db)["documents"], 1)
        self.assertEqual(kb.search(self.db, "retrieval")[0]["title"], "Agents")

    def test_search_ranks_relevant_first(self):
        kb.ingest(self.db, {"title": "Cooking", "body": "Pasta recipes.", "url": "https://example.com/c"})
        kb.ingest(self.db, {"title": "MCP", "body": "Model Context Protocol server for agents.", "url": "https://example.com/m"})
        hits = kb.search(self.db, "protocol agents")
        self.assertEqual([h["title"] for h in hits], ["MCP"])

    def test_search_tolerates_fts_syntax(self):
        kb.ingest(self.db, {"title": "MCP", "body": "server", "url": "https://example.com/m"})
        # FTS5 operators in user input are quoted as plain terms instead of raising.
        self.assertEqual([h["title"] for h in kb.search(self.db, 'server" OR ((')], ["MCP"])
        self.assertEqual(kb.search(self.db, '"( *'), [])

    def test_score_against_profile(self):
        profile = {"keywords": ["agents", "n8n"], "threshold": 0.5}
        self.assertEqual(kb.score({"title": "n8n agents", "body": ""}, profile), 1.0)
        self.assertEqual(kb.score({"title": "pasta", "body": ""}, profile), 0.0)

    def test_triage_keeps_only_relevant(self):
        profile = {"keywords": ["agents"], "threshold": 0.5}
        items = [
            {"title": "agents", "body": "x", "url": "https://example.com/1"},
            {"title": "pasta", "body": "x", "url": "https://example.com/2"},
        ]
        report = kb.triage(self.db, items, profile)
        self.assertEqual(report, {"inserted": 1, "updated": 0, "unchanged": 0, "rejected": 1})

    def test_long_query_does_not_raise(self):
        kb.ingest(self.db, {"title": "MCP", "body": "server", "url": "https://example.com/m"})
        self.assertEqual(kb.search(self.db, " ".join(f"w{i}" for i in range(300)) + " server")[0]["title"], "MCP")

    def test_notes_with_same_title_do_not_overwrite(self):
        from lumina import mcp_server
        with unittest.mock.patch.object(mcp_server, "db", self.db):
            mcp_server.add_note("Decision", "Use SQLite.")
            mcp_server.add_note("Decision", "Move to Postgres later.")
        self.assertEqual(kb.stats(self.db)["documents"], 2)

    def test_rejects_item_without_url(self):
        with self.assertRaises(ValueError):
            kb.ingest(self.db, {"title": "t", "body": "b"})


class RouterTest(unittest.TestCase):
    def test_routes_task_to_tier(self):
        self.assertEqual(router.route("classify"), "small")
        self.assertEqual(router.route("plan"), "large")
        self.assertEqual(router.route("unknown"), "medium")

    def test_empty_env_value_falls_back_to_offline(self):
        with unittest.mock.patch.dict(os.environ, {"LUMINA_MODEL_SMALL": ""}):
            self.assertEqual(router.model_for("summarize"), "offline-small")

    def test_offline_summary_is_first_sentence(self):
        self.assertEqual(router.complete("summarize", "First idea. Second idea."), "First idea.")


class ApiTest(unittest.TestCase):
    def test_ingest_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            server = api.make_server("127.0.0.1", 0, os.path.join(d, "t.db"), {"keywords": ["agents"], "threshold": 0.5})
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.server_address[1]
            body = json.dumps({"items": [{"title": "agents", "body": "b", "url": "https://example.com/1"}]}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/ingest", body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(json.load(r)["inserted"], 1)
            bad = urllib.request.Request(f"http://127.0.0.1:{port}/ingest", b"not json", {"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(bad)
            self.assertEqual(e.exception.code, 400)
            server.shutdown()
            server.server_close()

    def _post(self, port, body, headers):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.putrequest("POST", "/ingest")
        for k, v in headers.items():
            conn.putheader(k, v)
        conn.endheaders(body)
        status = conn.getresponse().status
        conn.close()
        return status

    def test_rejects_unsafe_requests(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = os.path.join(d, "t.db")
            server = api.make_server("127.0.0.1", 0, db_path, {"keywords": ["agents"], "threshold": 0.5})
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.server_address[1]
            ok = {"title": "agents", "body": "b", "url": "https://example.com/1"}
            payload = json.dumps({"items": [ok]}).encode()
            # A browser "simple request" (text/plain) must not be able to write.
            self.assertEqual(self._post(port, payload, {"Content-Type": "text/plain", "Content-Length": str(len(payload))}), 415)
            js = {"Content-Type": "application/json"}
            self.assertEqual(self._post(port, b"", dict(js, **{"Content-Length": "-5"})), 400)
            self.assertEqual(self._post(port, b"", dict(js, **{"Content-Length": "abc"})), 400)
            # One bad item rejects the whole batch and writes nothing.
            batch = json.dumps({"items": [ok, {"title": None, "body": "b", "url": "https://example.com/2"}, 3]}).encode()
            self.assertEqual(self._post(port, batch, dict(js, **{"Content-Length": str(len(batch))})), 400)
            self.assertEqual(kb.stats(kb.connect(db_path))["documents"], 0)
            server.shutdown()
            server.server_close()

    def test_provider_error_returns_502(self):
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(os.environ, {"LUMINA_MODEL_SMALL": "real-model"}):
            server = api.make_server("127.0.0.1", 0, os.path.join(d, "t.db"), {"keywords": ["agents"], "threshold": 0.5})
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.server_address[1]
            body = json.dumps({"items": [{"title": "agents", "body": "b", "url": "https://example.com/1"}]}).encode()
            self.assertEqual(self._post(port, body, {"Content-Type": "application/json", "Content-Length": str(len(body))}), 502)
            server.shutdown()
            server.server_close()


class McpTest(unittest.TestCase):
    def test_tools_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["LUMINA_DB"] = os.path.join(d, "m.db")
            from lumina import mcp_server

            async def run():
                await mcp_server.mcp.call_tool("add_note", {"title": "Decision", "body": "Use SQLite FTS5 for retrieval."})
                _, out = await mcp_server.mcp.call_tool("search_knowledge", {"query": "retrieval"})
                return out

            out = asyncio.run(run())
            self.assertEqual(out["result"][0]["title"], "Decision")


if __name__ == "__main__":
    unittest.main()
