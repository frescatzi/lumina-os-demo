"""MCP server: exposes the knowledge base to any MCP client (Claude Desktop, Claude Code, agents)."""
import hashlib
import os

from mcp.server.fastmcp import FastMCP

from lumina import kb

mcp = FastMCP("lumina-knowledge")
db = kb.connect(os.environ.get("LUMINA_DB", "data/lumina.db"))


@mcp.tool()
def search_knowledge(query: str, limit: int = 5) -> list[dict]:
    """Full-text search over the knowledge base, best matches first."""
    return kb.search(db, query, max(1, min(limit, 20)))


@mcp.tool()
def get_document(doc_id: str) -> dict:
    """Return one document with its full body."""
    return kb.get(db, doc_id) or {"error": f"no document {doc_id}"}


@mcp.tool()
def add_note(title: str, body: str) -> str:
    """Write an agent's note or decision back into the knowledge base."""
    # Identity includes the body, so two decisions with the same title are both kept.
    note_id = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()[:16]
    return kb.ingest(db, {"title": title, "body": body, "url": f"note:{note_id}", "source": "agent"})


@mcp.tool()
def knowledge_stats() -> dict:
    """Document count and last update time."""
    return kb.stats(db)


if __name__ == "__main__":
    mcp.run()
