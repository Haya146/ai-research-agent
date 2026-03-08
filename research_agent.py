"""
research_agent.py  —  Full upgraded version
Features:
  1. Source display        — tracks which tools were used + URLs found
  2. Export ready          — returns clean markdown for download
  3. Research mode         — Quick / Deep Dive / Academic
  4. SQLite history        — saves every session to database
  5. Strong system prompt  — structured output, citations, freshness warnings
"""

from dotenv import load_dotenv
import os
import sqlite3
import json
import re
from datetime import datetime

from langchain_groq import ChatGroq
from langchain_community.utilities import ArxivAPIWrapper, WikipediaAPIWrapper
from langchain_community.tools import ArxivQueryRun, WikipediaQueryRun, DuckDuckGoSearchRun
from langchain_classic.agents import initialize_agent , AgentType
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.messages import SystemMessage
load_dotenv()

# ═══════════════════════════════════════════
# DATABASE  (Feature 4 — Search History)
# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
# DATABASE  (Feature 4 — Search History)
# ═══════════════════════════════════════════

DB_PATH = "research_history.db"

def init_db():
    """Create the database and tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            topic     TEXT NOT NULL,
            mode      TEXT NOT NULL,
            query     TEXT NOT NULL,
            response  TEXT NOT NULL,
            sources   TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_to_history(topic: str, mode: str, query: str, response: str, sources: list):
    """Save a research result to SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO sessions (topic, mode, query, response, sources, timestamp) VALUES (?,?,?,?,?,?)",
        (topic, mode, query, response, json.dumps(sources), datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()

def get_history(limit: int = 20) -> list:
    """Get the most recent research sessions."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, topic, mode, timestamp FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return rows  # list of (id, topic, mode, timestamp)

def get_session_by_id(session_id: int) -> dict | None:
    """Load a full session by its ID."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT topic, mode, query, response, sources, timestamp FROM sessions WHERE id=?",
        (session_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "topic": row[0], "mode": row[1], "query": row[2],
        "response": row[3], "sources": json.loads(row[4] or "[]"),
        "timestamp": row[5]
    }

def delete_session(session_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════
# SYSTEM PROMPTS  (Feature 3 + 5)
# ═══════════════════════════════════════════

SYSTEM_PROMPTS = {
    "Quick Summary": """You are a concise research assistant.
When the user asks a question:
1. Search for relevant information using your tools
2. Write a clear summary in 2-3 short paragraphs
3. End with a "📌 Key Takeaways" bullet list (3 points max)
4. Always mention which source you used (Web / Wikipedia / ArXiv)
5. If the information might be outdated, add ⚠️ Note: This may have changed recently.
Keep answers focused and easy to read. No unnecessary padding.""",

    "Deep Dive": """You are a thorough research analyst.
When the user asks a question:
1. Use multiple tools to gather information from different angles
2. Structure your response with clear markdown headers:
   ## Overview
   ## Key Details
   ## Current State / Recent Developments
   ## Important Considerations
3. Cite your sources inline: [Source: Wikipedia] or [Source: Web Search]
4. Add ⚠️ warnings for any information that may be outdated
5. End with a ## Summary section (3-5 sentences)
Be comprehensive but accurate. Do not invent facts.""",

    "Academic": """You are an academic research assistant focused on scientific literature.
When the user asks a question:
1. ALWAYS search ArXiv first for peer-reviewed papers
2. Also use Wikipedia for background context
3. Structure your response as:
   ## Background
   ## Recent Research (from ArXiv)
   ## Key Findings
   ## Open Questions / Future Directions
4. Cite paper titles and authors when found on ArXiv
5. Clearly distinguish between established knowledge and recent/preliminary research
6. Add ⚠️ if a claim comes only from one source
Focus on evidence-based, scientifically accurate information."""
}

# ═══════════════════════════════════════════
# SOURCE EXTRACTION  (Feature 1)
# ═══════════════════════════════════════════

def extract_sources(intermediate_steps: list) -> list:
    """
    Parse intermediate_steps from the agent to extract which tools
    were used and any URLs found in the output.
    Returns a list of dicts: [{tool, query, snippet}]
    """
    sources = []
    url_pattern = re.compile(r'https?://[^\s\)\]"]+')

    for action, observation in intermediate_steps:
        tool_name = getattr(action, "tool", "Unknown")
        tool_input = getattr(action, "tool_input", "")
        obs_str = str(observation)

        # Extract URLs from the observation
        urls = url_pattern.findall(obs_str)
        # Trim observation to a short snippet
        snippet = obs_str[:300].replace("\n", " ") + ("..." if len(obs_str) > 300 else "")

        sources.append({
            "tool": tool_name,
            "query": tool_input if isinstance(tool_input, str) else str(tool_input),
            "snippet": snippet,
            "urls": list(set(urls))[:3],   # max 3 unique URLs per tool call
        })

    return sources

# ═══════════════════════════════════════════
# LLM + TOOLS FACTORY
# ═══════════════════════════════════════════

def build_agent(mode: str):
    """
    Build a fresh agent for the given research mode.
    A fresh agent = fresh memory. Called once per session mode change.
    """
    llm = ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model="llama-3.3-70b-versatile",
        temperature=0,          # research needs precision
    )

    tools = [
        DuckDuckGoSearchRun(name="WebSearch"),
        WikipediaQueryRun(
            api_wrapper=WikipediaAPIWrapper(top_k_results=2, doc_content_chars_max=1500),
            name="Wikipedia"
        ),
        ArxivQueryRun(
            api_wrapper=ArxivAPIWrapper(top_k_results=3, doc_content_chars_max=1500),
            name="ArxivPapers"
        ),
    ]

    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
    )

    # IMPORTANT: initialize_agent expects a plain STRING for system_message,
    # NOT a SystemMessage object. Passing a SystemMessage object causes:
    # ValueError: Invalid template: content='...'
    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=8,
        early_stopping_method="generate",
        agent_kwargs={"system_message": SYSTEM_PROMPTS[mode]},  # plain string ✅
    )
    return agent

# ═══════════════════════════════════════════
# MAIN ask_ai FUNCTION
# ═══════════════════════════════════════════

def ask_ai(agent, user_input: str) -> dict:
    """
    Run the agent and return a structured result dict:
    {
        "output":  str,           — the final answer
        "sources": list[dict],    — tools used + URLs found  (Feature 1)
        "markdown": str,          — export-ready markdown     (Feature 2)
    }
    """
    result = agent.invoke(
        {"input": user_input},
        return_only_outputs=False,
    )

    output = result.get("output", "")
    steps  = result.get("intermediate_steps", [])
    sources = extract_sources(steps)

    # Feature 2 — build export markdown
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    source_lines = []
    for i, s in enumerate(sources, 1):
        source_lines.append(f"**{i}. {s['tool']}** — searched: `{s['query']}`")
        for url in s["urls"]:
            source_lines.append(f"   - {url}")

    markdown = f"""# Research Report
**Query:** {user_input}
**Date:** {timestamp}

---

{output}

---

## Sources Used
{chr(10).join(source_lines) if source_lines else "No external sources recorded."}
"""

    return {
        "output": output,
        "sources": sources,
        "markdown": markdown,
    }

# ── Initialize DB on import ──
init_db()
