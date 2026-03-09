
import streamlit as st
import uuid
from research_agent import (
    ask_ai,
    build_agent,
    get_history,
    get_session_by_id,
    save_to_history,
    delete_session,
)

# ═══════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════
st.set_page_config(
    page_title="AI Research Agent",
    page_icon="🔬",
    layout="wide",
)


if "messages"       not in st.session_state: st.session_state["messages"]      = []
if "session_id"     not in st.session_state: st.session_state["session_id"]    = str(uuid.uuid4())
if "current_mode"   not in st.session_state: st.session_state["current_mode"]  = "Quick Summary"
if "agent"          not in st.session_state: st.session_state["agent"]         = build_agent("Quick Summary")
if "prefill_input"  not in st.session_state: st.session_state["prefill_input"] = None

with st.sidebar:
    st.title("🔬 AI Research Agent")
    st.markdown("---")

    st.markdown("### ⚙️ Research Mode")
    mode = st.radio(
        label="Choose how deep to research:",
        options=["Quick Summary", "Deep Dive", "Academic"],
        index=["Quick Summary", "Deep Dive", "Academic"].index(st.session_state["current_mode"]),
        help=(
            "**Quick Summary** — 2-3 paragraphs, key takeaways\n\n"
            "**Deep Dive** — Full structured report with headers\n\n"
            "**Academic** — ArXiv-first, paper citations, scientific focus"
        ),
    )

    if mode != st.session_state["current_mode"]:
        st.session_state["current_mode"] = mode
        st.session_state["agent"]        = build_agent(mode)
        st.session_state["messages"]     = []
        st.info(f"Switched to **{mode}** mode. Conversation reset.")

    st.markdown("---")

    st.markdown("### 🛠️ Active Tools")
    st.markdown("🌐 **DuckDuckGo** — Web search")
    st.markdown("📖 **Wikipedia** — Encyclopedia")
    st.markdown("📄 **ArXiv** — Research papers")

    st.markdown("---")

    st.markdown("### 💡 Try These")
    examples = {
        "Quick Summary": [
            "Latest breakthroughs in quantum computing 2024",
            "How does CRISPR gene editing work?",
            "What is LangChain and how is it used?",
        ],
        "Deep Dive": [
            "Explain the transformer architecture in AI",
            "History and current state of fusion energy",
            "How does the human immune system fight viruses?",
        ],
        "Academic": [
            "Recent ArXiv papers on LLM hallucination",
            "Advances in protein structure prediction 2024",
            "State of the art in reinforcement learning from human feedback",
        ],
    }
    for ex in examples[mode]:
        if st.button(ex, key=f"ex_{ex}", use_container_width=True):
            st.session_state["prefill_input"] = ex
            st.rerun()

    st.markdown("---")

    st.markdown("### 🕒 Research History")
    history = get_history(limit=15)

    if not history:
        st.caption("No research history yet.")
    else:
        for row_id, topic, h_mode, timestamp in history:
            col1, col2 = st.columns([5, 1])
            with col1:
                label = f"{'⚡' if h_mode=='Quick Summary' else '🔍' if h_mode=='Deep Dive' else '🎓'} {topic[:32]}{'...' if len(topic)>32 else ''}"
                if st.button(label, key=f"hist_{row_id}", use_container_width=True,
                             help=f"{h_mode} • {timestamp}"):
                    st.session_state["load_session_id"] = row_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{row_id}", help="Delete"):
                    delete_session(row_id)
                    st.rerun()

    st.markdown("---")

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state["messages"]   = []
        st.session_state["session_id"] = str(uuid.uuid4())
        st.session_state["agent"]      = build_agent(st.session_state["current_mode"])
        st.rerun()

    st.caption("Powered by Groq · LLaMA 3.3 70B")


if "load_session_id" in st.session_state:
    loaded = get_session_by_id(st.session_state.pop("load_session_id"))
    if loaded:
        st.session_state["messages"] = [
            {"role": "user",      "content": loaded["query"],    "sources": []},
            {"role": "assistant", "content": loaded["response"], "sources": loaded["sources"]},
        ]
        if loaded["mode"] != st.session_state["current_mode"]:
            st.session_state["current_mode"] = loaded["mode"]
            st.session_state["agent"]        = build_agent(loaded["mode"])

mode_badge = {"Quick Summary": "⚡ Quick Summary", "Deep Dive": "🔍 Deep Dive", "Academic": "🎓 Academic"}
st.title("🔬 AI Research Agent")
st.caption(
    f"Current mode: **{mode_badge[st.session_state['current_mode']]}**  •  "
    "Ask me anything — I search the Web, Wikipedia, and ArXiv to give you sourced answers."
)
st.divider()

def render_assistant_message(content: str, sources: list, query: str = ""):
    """Render the assistant bubble with sources panel and download button."""
    st.markdown(content)

    if sources:
        with st.expander(f"🔎 Sources used ({len(sources)} tool call{'s' if len(sources)>1 else ''})", expanded=False):
            for i, s in enumerate(sources, 1):
                tool_emoji = {"WebSearch": "🌐", "Wikipedia": "📖", "ArxivPapers": "📄"}.get(s["tool"], "🔧")
                st.markdown(f"**{tool_emoji} {s['tool']}** — searched: `{s['query']}`")
                if s.get("urls"):
                    for url in s["urls"]:
                        st.markdown(f"  - [{url}]({url})")
                if s.get("snippet"):
                    st.caption(f"> {s['snippet'][:200]}...")
                if i < len(sources):
                    st.markdown("---")

    timestamp = ""
    for m in st.session_state["messages"]:
        if m["content"] == content:
            timestamp = ""
            break

    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    source_lines = []
    for s in sources:
        source_lines.append(f"**{s['tool']}** — `{s['query']}`")
        for url in s.get("urls", []):
            source_lines.append(f"  - {url}")

    export_md = f"""# Research Report
**Query:** {query}
**Mode:** {st.session_state['current_mode']}
**Date:** {ts}

---

{content}

---

## Sources Used
{chr(10).join(source_lines) if source_lines else "No external sources recorded."}
"""
    st.download_button(
        label="📥 Download as Markdown",
        data=export_md,
        file_name=f"research_{ts[:10]}.md",
        mime="text/markdown",
        key=f"dl_{hash(content)}",
    )

for i, message in enumerate(st.session_state["messages"]):
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            query = ""
            if i > 0 and st.session_state["messages"][i-1]["role"] == "user":
                query = st.session_state["messages"][i-1]["content"]
            render_assistant_message(
                message["content"],
                message.get("sources", []),
                query=query,
            )
        else:
            st.markdown(message["content"])


prefill    = st.session_state.pop("prefill_input", None)
user_input = st.chat_input("Search anything...") or prefill

if user_input:
    # Show user message
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state["messages"].append({"role": "user", "content": user_input})


    with st.chat_message("assistant"):
        with st.spinner(f"🔍 Researching in **{st.session_state['current_mode']}** mode..."):
            result = ask_ai(st.session_state["agent"], user_input)

        render_assistant_message(result["output"], result["sources"], query=user_input)


    st.session_state["messages"].append({
        "role":    "assistant",
        "content": result["output"],
        "sources": result["sources"],
    })

    topic = user_input[:50]
    save_to_history(
        topic   = topic,
        mode    = st.session_state["current_mode"],
        query   = user_input,
        response= result["output"],
        sources = result["sources"],
    )
