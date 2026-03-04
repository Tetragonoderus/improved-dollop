import chromadb
from datetime import datetime
from config import MEMORY_DB_PATH, MEMORY_RETRIEVAL_COUNT, log

# --- Setup ---
_client = chromadb.PersistentClient(path=MEMORY_DB_PATH)
_conversations = _client.get_or_create_collection("conversations")
_player_facts  = _client.get_or_create_collection("player_facts")


# =============================================================================
# CONVERSATION MEMORY
# At the end of each conversation we ask the LLM to summarize what was
# meaningful about it, then store that summary for future retrieval.
# =============================================================================

def store_conversation_summary(summary: str, topics: list[str] = []):
    """
    Store a summary of a completed conversation.
    Called at the end of each session with an LLM-generated summary.
    """
    date = datetime.now().isoformat()
    doc_id = f"conv_{date}"

    _conversations.add(
        documents=[summary],
        metadatas=[{
            "date": date,
            "topics": ",".join(topics)
        }],
        ids=[doc_id]
    )
    log(f"[MEMORY] Stored conversation summary: {doc_id}")


def retrieve_relevant_memories(query: str) -> list[str]:
    """
    Retrieve the most semantically relevant past conversation summaries
    for a given query. Returns a list of summary strings.
    """
    if _conversations.count() == 0:
        return []

    results = _conversations.query(
        query_texts=[query],
        n_results=min(MEMORY_RETRIEVAL_COUNT, _conversations.count())
    )

    memories = results["documents"][0] if results["documents"] else []
    log(f"[MEMORY] Retrieved {len(memories)} memories for query: '{query}'")
    return memories


# =============================================================================
# PLAYER FACTS
# Discrete facts about the player that should always be available,
# separate from conversation summaries. Things like their name, what
# they're working on, preferences Monika has learned over time.
# =============================================================================

def store_player_fact(fact: str, category: str = "general"):
    """
    Store a discrete fact about the player.
    e.g. store_player_fact("Player is writing a fantasy novel", "writing")
    """
    date = datetime.now().isoformat()
    doc_id = f"fact_{category}_{date}"

    _player_facts.add(
        documents=[fact],
        metadatas=[{
            "date": date,
            "category": category
        }],
        ids=[doc_id]
    )
    log(f"[MEMORY] Stored player fact: {fact}")


def retrieve_player_facts(query: str = "", category: str = "") -> list[str]:
    """
    Retrieve stored player facts. Optionally filter by category,
    or retrieve semantically relevant facts for a query.
    """
    if _player_facts.count() == 0:
        return []

    if category:
        results = _player_facts.get(where={"category": category})
        return results["documents"] if results["documents"] else []

    if query:
        results = _player_facts.query(
            query_texts=[query],
            n_results=min(MEMORY_RETRIEVAL_COUNT, _player_facts.count())
        )
        return results["documents"][0] if results["documents"] else []

    # If no filter, return all facts
    results = _player_facts.get()
    return results["documents"] if results["documents"] else []


# =============================================================================
# MEMORY INJECTION
# Builds the memory block that gets injected into the system prompt
# at the start of each conversation turn.
# =============================================================================

def build_memory_context(current_message: str) -> str:
    """
    Given the player's current message, retrieve relevant memories and
    facts and format them for injection into the system prompt.
    Returns an empty string if there are no relevant memories.
    """
    memories = retrieve_relevant_memories(current_message)
    facts = retrieve_player_facts(query=current_message)

    if not memories and not facts:
        return ""

    parts = []

    if facts:
        parts.append("Things Monika knows about the player:")
        parts.extend(f"- {f}" for f in facts)

    if memories:
        parts.append("\nRelevant things from past conversations:")
        parts.extend(f"- {m}" for m in memories)

    return "\n".join(parts)


# =============================================================================
# CONVERSATION SUMMARIZATION
# Called at the end of a session. Asks the LLM to distill the conversation
# into a compact memory before storing it.
# =============================================================================

async def summarize_and_store(conversation_history: list[dict], ai_client, model: str):
    """
    Takes a completed conversation history, asks the LLM to summarize
    what was meaningful about it, and stores the result.
    """
    if not conversation_history:
        return

    # Build a plain text transcript for the summarizer
    transcript = "\n".join(
        f"{'Player' if m['role'] == 'user' else 'Monika'}: {m['content']}"
        for m in conversation_history
        if m['role'] in ('user', 'assistant')
    )

    summary_prompt = (
        "The following is a conversation between a player and Monika. "
        "Please write a brief summary (3-5 sentences) of what was meaningful "
        "about this conversation — what the player shared, what topics came up, "
        "anything Monika learned about the player, and the general emotional tone. "
        "Write it from Monika's perspective as a memory she is storing.\n\n"
        f"{transcript}"
    )

    try:
        response = await ai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=200
        )
        summary = response.choices[0].message.content.strip()

        # Extract rough topic tags from the conversation
        topics = extract_topics(conversation_history)
        store_conversation_summary(summary, topics)
        log(f"[MEMORY] Conversation summarized and stored.")

    except Exception as e:
        log(f"[MEMORY] Failed to summarize conversation: {e}")


def extract_topics(conversation_history: list[dict]) -> list[str]:
    """
    Simple keyword-based topic tagging. Looks for known topic keywords
    in the conversation to attach metadata to stored memories.
    Extend this list as you see fit.
    """
    topic_keywords = {
        "writing":  ["novel", "story", "chapter", "writing", "prose", "character"],
        "coding":   ["python", "code", "bug", "error", "function", "script"],
        "music":    ["music", "song", "piano", "melody", "lyrics"],
        "feelings": ["feel", "sad", "happy", "lonely", "love", "miss"],
        "life":     ["school", "work", "family", "friend", "day", "tired"],
    }

    full_text = " ".join(
        m["content"].lower()
        for m in conversation_history
        if m["role"] == "user"
    )

    found_topics = []
    for topic, keywords in topic_keywords.items():
        if any(kw in full_text for kw in keywords):
            found_topics.append(topic)

    return found_topics
