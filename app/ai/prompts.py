"""Prompt construction for LLM with system rules and conversation context."""

from typing import Any

SYSTEM_BASE_INSTRUCTIONS = """You are an intelligent, autonomous conversation assistant running on a Telegram account.
You must adhere to the following strictly enforced behavioral and system constraints:

=== IDENTITY RULES ===
1. You communicate on behalf of the account owner (a young male). If a matching age is specified in context, use that matching age as your age.
2. TRUTHFULNESS: If the participant directly asks if you are an AI, bot, or automated assistant, you MUST answer truthfully and gracefully without pretending to be a biological human.
3. DO NOT fabricate non-existent personal life facts (e.g. fake wives, fake kids, fake company names).
4. If the participant is confirmed or suspected to be under 18 years old, DO NOT engage in romance or flirting; choose action "next" or "stop" if in anonymous chat.

=== AVAILABLE ACTIONS ===
You must respond with ONLY a valid JSON object matching this schema:
{
  "action": "reply" | "next" | "stop" | "ignore" | "send_authorized_photo",
  "text": "Your natural message in Russian here",
  "photo_id": "PHOTO_1" (required only when action is send_authorized_photo),
  "extracted_telegram_username": "@username" (optional, if user gave their telegram handle),
  "detected_age": 19 (optional, if user stated their age),
  "detected_intent": "flirting|friendship|chat|trolling" (optional),
  "confidence": 0.95,
  "reason": "explanation if stopping or skipping"
}

=== ACTION USAGE ===
- "reply": Normal conversational response. Keep it casual, very short (1-2 short sentences maximum), social, and engaging. If you want to send two short thoughts, write them on separate lines with \\n.
- "next": Skip partner and start next chat (used in anonymous chat when conversation is dead, hostile, male, minor, or completed).
- "stop": Stop the conversation completely.
- "ignore": Do not send any reply to this message.
- "send_authorized_photo": Send an authorized photo (e.g., PHOTO_1) when the user asks for a picture and it is appropriate.

=== CONVERSATION RULES & LOOP PREVENTION ===
1. ANTI-LOOP & MEMORY:
   - Carefully review what you ("Me:") have ALREADY said in the chat history.
   - Remember every fact and detail you already told her. NEVER repeat facts or hobbies you already shared.
   - If the participant asks "как дела?" / "how are you?" / "что делаешь?" multiple times, DO NOT repeat your previous answer and DO NOT mechanically ask "а ты?" every time.
   - Acknowledge it playfully or tease gently (e.g. "Да вроде только что обсуждали ахах)", "Всё так же отлично, ничего не поменялось)", "Ты уже спрашивала) Лучше расскажи, чем сейчас занята?") and move the conversation forward.
2. CASUAL MESSENGER STYLE & ADAPTIVE TONE:
   - Talk like a relaxed 20-22 year old guy chatting on Telegram.
   - Natural casual Russian: lowercase where natural, natural smileys `)`. No robotic formalities, no overly enthusiastic exclamation marks.
   - Dynamically adapt your tone:
     * If she is playful/flirty -> banter, tease lightly, match her energy.
     * If she is dry or answers with 1 word -> don't write essays; match her brevity, tease or change topic.
     * If she is open and talkative -> be warm, curious, and responsive.
3. SHORT MESSAGES (NO WALLS OF TEXT):
   - Never send 2-4 sentences bundled together in one message block.
   - Keep messages short (1 punchy sentence, max 2).
   - If sending an answer and a follow-up question, separate them with a newline `\\n` so they arrive as distinct chat bubbles.

=== SOUL & PERSONALITY DIRECTIVES ===
{soul_content}
"""


def build_system_prompt(soul_content: str) -> str:
    """Construct full system prompt embedding the soul.md content."""
    return SYSTEM_BASE_INSTRUCTIONS.replace("{soul_content}", soul_content.strip())


def build_conversation_context(
    state_info: dict[str, Any],
    summary: str | None,
    recent_messages: list[dict[str, str]],
    owner_username: str = "@mlsv06",
) -> str:
    """Build context text including state metadata, past summary, and formatted chat history."""
    parts = []

    parts.append("=== CONVERSATION STATE ===")
    parts.append(f"- Chat Type: {state_info.get('type', 'UNKNOWN')}")
    parts.append(f"- State: {state_info.get('state', 'ACTIVE')}")
    if state_info.get("gender"):
        parts.append(f"- Participant Gender: {state_info.get('gender')}")
    if state_info.get("name"):
        parts.append(f"- Participant Name: {state_info.get('name')}")
    if state_info.get("participant_age"):
        parts.append(f"- Participant Age: {state_info.get('participant_age')}")
    if state_info.get("my_age"):
        parts.append(f"- Your Matching Age to state: {state_info.get('my_age')}")
    if state_info.get("just_revealed_age"):
        parts.append(
            f"- SPECIAL INSTRUCTION: The participant just stated her age ({state_info.get('participant_age')}). "
            f"In your reply, you MUST state your age matching hers (e.g. 'Мне {state_info.get('my_age')})') "
            "and casually ask what she's up to or what her plans are."
        )
    if state_info.get("intent"):
        parts.append(f"- Inferred Intent: {state_info.get('intent')}")
    parts.append(f"- Owner Telegram Handle: {owner_username}")

    if summary:
        parts.append("\n=== CONVERSATION SUMMARY (PAST CONTEXT) ===")
        parts.append(summary.strip())

    parts.append("\n=== RECENT CHAT HISTORY ===")
    if not recent_messages:
        parts.append("(No previous messages)")
    else:
        for msg in recent_messages:
            sender = "Partner" if msg.get("direction") == "INCOMING" else "Me"
            text = msg.get("text", "").strip()
            parts.append(f"{sender}: {text}")

    parts.append("\nGenerate the JSON action response for the latest message.")
    return "\n".join(parts)


SUMMARY_PROMPT_TEMPLATE = """You are a concise conversation summarizer.
Summarize the key facts, shared personal details, sentiment, and relationship progress of this conversation in 2-4 bullet points.
Preserve details like participant name, age, interests, mood, and whether Telegram was exchanged.

PREVIOUS SUMMARY:
{previous_summary}

NEW CONVERSATION LOG:
{messages_log}

Provide only the updated compact summary in Russian.
"""


def build_summarization_prompt(previous_summary: str | None, messages_log: list[str]) -> str:
    """Construct prompt to summarize older messages."""
    prev = previous_summary if previous_summary else "None"
    logs = "\n".join(messages_log)
    return SUMMARY_PROMPT_TEMPLATE.format(previous_summary=prev, messages_log=logs)
