"""Slack bot that answers questions about Google Sheets data."""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Load .env.local first (user's private keys), then .env as fallback
load_dotenv(Path(__file__).parent.parent / ".env.local")
load_dotenv(Path(__file__).parent.parent / ".env")

import litellm
from slack_bolt import App, Assistant
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .sheets import SheetsClient

# --- Framing ---

PROJECT_ROOT = Path(__file__).parent.parent
FRAMING_PATH = Path(os.environ.get("FRAMING_PATH", str(PROJECT_ROOT / "FRAMING.md")))

_framing_cache: str | None = None


def _load_framing() -> str:
    """Load framing from BOT_FRAMING env var, or FRAMING.md file."""
    global _framing_cache
    env_framing = os.environ.get("BOT_FRAMING")
    if env_framing:
        _framing_cache = env_framing
    else:
        try:
            _framing_cache = FRAMING_PATH.read_text()
        except FileNotFoundError:
            _framing_cache = "You are a helpful data assistant."
    return _framing_cache


def _get_framing() -> str:
    """Get current framing content."""
    if _framing_cache is None:
        _load_framing()
    return _framing_cache


# --- Tool definitions (OpenAI function calling format) ---

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Free-text search across all columns. Returns matching rows with _tab indicating source tab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for (case-insensitive, matches any column)",
                    },
                    "tab": {
                        "type": "string",
                        "description": "Tab name to search in. Omit to search all tabs.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 50)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query",
            "description": "Structured query with filters, amount range, date range, and sorting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {
                        "type": "string",
                        "description": "Tab name to query. Defaults to first tab.",
                    },
                    "filters": {
                        "type": "object",
                        "description": 'Column name -> substring match (e.g. {"Name": "Acme"})',
                        "additionalProperties": {"type": "string"},
                    },
                    "amount_column": {
                        "type": "string",
                        "description": "Column containing amounts to filter on",
                    },
                    "min_amount": {"type": "number", "description": "Minimum amount"},
                    "max_amount": {"type": "number", "description": "Maximum amount"},
                    "date_column": {
                        "type": "string",
                        "description": "Column containing dates to filter on",
                    },
                    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "sort_by": {"type": "string", "description": "Column to sort by"},
                    "sort_desc": {
                        "type": "boolean",
                        "description": "Sort descending (default true)",
                    },
                    "limit": {"type": "integer", "description": "Max rows (default 50)"},
                },
                "required": [],
            },
        },
    },
]


def execute_tool(name: str, inputs: dict, sheets: SheetsClient) -> dict:
    if name == "search":
        return sheets.search(**inputs)
    elif name == "query":
        return sheets.query(**inputs)
    else:
        return {"error": f"Unknown tool: {name}"}


# --- LLM integration ---

BOT_INSTRUCTIONS = (
    "Use the provided tools to look up data. The spreadsheet schema is included below "
    "so you do NOT need to call get_schema — go straight to search or query.\n\n"
    "FORMATTING: Your responses will be displayed in Slack. Use Slack mrkdwn formatting:\n"
    "- *bold* for emphasis (NOT **bold**)\n"
    "- Use numbered lists, not markdown tables (Slack doesn't render tables)\n"
    "- Use ` for inline code, ``` for code blocks\n"
    "- Keep responses compact — no emoji, no filler\n\n"
    "IMPORTANT: End every response with a JSON block on its own line like this:\n"
    '```followups\n'
    '["question 1", "question 2", "question 3"]\n'
    "```\n"
    "These should be 2-3 short follow-up questions to dig deeper into the data. "
    "Do NOT include a 'Want to dig deeper?' header — just end with the JSON block."
)

DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"


def _build_system_prompt(schema: dict) -> str:
    """Build system prompt from framing file + bot instructions + pre-loaded schema."""
    framing = _get_framing()
    schema_text = json.dumps(schema, indent=2, default=str)
    return (
        f"{framing}\n\n---\n\n{BOT_INSTRUCTIONS}\n\n"
        f"## Spreadsheet Schema\n\n```json\n{schema_text}\n```"
    )


def ask_llm(question: str, sheets: SheetsClient, schema: dict, history: list[dict] | None = None) -> dict:
    """Returns {"answer": str, "followups": list[str]}."""
    if history:
        messages = history + [{"role": "user", "content": question}]
    else:
        messages = [{"role": "user", "content": question}]
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    system_prompt = _build_system_prompt(schema)

    # Prepend system message
    all_messages = [{"role": "system", "content": system_prompt}] + messages

    for _ in range(5):
        response = litellm.completion(
            model=model,
            max_tokens=1024,
            tools=TOOLS,
            messages=all_messages,
        )

        choice = response.choices[0]
        if choice.finish_reason != "tool_calls":
            return _parse_response(choice.message.content or "")

        # Handle tool calls
        all_messages.append(choice.message)
        for tool_call in choice.message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            result = execute_tool(tool_call.function.name, args, sheets)
            all_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

    return {"answer": "Sorry, I couldn't resolve your question after several attempts.", "followups": []}


def _parse_response(raw: str) -> dict:
    """Extract answer text and followup questions from the response."""
    followups = []
    match = re.search(r"```followups\s*\n(.+?)\n```", raw, re.DOTALL)
    if match:
        try:
            followups = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
        answer = raw[:match.start()].rstrip()
    else:
        answer = raw.rstrip()
    return {"answer": answer, "followups": followups}


def _get_thread_history(client, channel: str, thread_ts: str) -> list[dict]:
    """Fetch thread messages and convert to message format.

    Excludes the latest user message (that's passed separately as the question).
    Strips the followups JSON blocks from bot responses.
    """
    try:
        result = client.conversations_replies(channel=channel, ts=thread_ts, limit=50)
        messages = result.get("messages", [])
    except Exception:
        return []

    history = []
    bot_user_id = None
    try:
        auth = client.auth_test()
        bot_user_id = auth.get("user_id")
    except Exception:
        pass

    # Skip first message (greeting) and last message (current question)
    for msg in messages[1:-1]:
        text = msg.get("text", "").strip()
        if not text:
            continue

        # Strip followups JSON from bot responses
        text = re.sub(r"```followups\s*\n.+?\n```", "", text, flags=re.DOTALL).rstrip()
        if not text:
            continue

        if msg.get("bot_id") or (bot_user_id and msg.get("user") == bot_user_id):
            role = "assistant"
        else:
            role = "user"

        # Avoid consecutive same-role messages
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n" + text
        else:
            history.append({"role": role, "content": text})

    return history


# --- Default prompts shown when users open the assistant ---

DEFAULT_PROMPTS = [
    {"title": "What data is available?", "message": "What tabs and columns are in this spreadsheet?"},
    {"title": "Summary", "message": "Give me a high-level summary of the data"},
    {"title": "Top entries", "message": "What are the top entries by value?"},
    {"title": "Recent entries", "message": "Show me the most recent entries"},
]


# --- Slack bot ---


def main():
    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    spreadsheet_url = os.environ.get("SHEETS_SPREADSHEET_URL")
    if not spreadsheet_url:
        raise RuntimeError("SHEETS_SPREADSHEET_URL environment variable is required")
    sheets_client = SheetsClient(spreadsheet_url)
    schema = sheets_client.get_schema()
    bot_user_id = app.client.auth_test()["user_id"]
    print(f"Pre-loaded schema: {len(schema['tabs'])} tabs")

    assistant = Assistant()

    @assistant.thread_started
    def handle_thread_started(say, set_suggested_prompts):
        say("Hi! I can answer questions about your spreadsheet data. Ask me anything or pick a suggestion below.")
        set_suggested_prompts(prompts=DEFAULT_PROMPTS, title="Try asking:")

    @assistant.user_message
    def handle_user_message(payload, say, set_status, set_title, set_suggested_prompts, client):
        question = payload.get("text", "")
        channel = payload["channel"]
        thread_ts = payload.get("thread_ts", payload["ts"])

        set_title(question[:60])

        # Post a placeholder while thinking
        placeholder = client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="_Thinking..._",
        )

        # Fetch thread history for conversation context
        history = _get_thread_history(client, channel, thread_ts)

        try:
            result = ask_llm(question, sheets_client, schema, history=history)
            # Use plain text blocks (no action buttons) — DMs use set_suggested_prompts instead
            answer_blocks = _build_blocks({"answer": result["answer"], "followups": []})
            client.chat_update(
                channel=channel,
                ts=placeholder["ts"],
                text=result["answer"],
                blocks=answer_blocks,
            )

            if result["followups"]:
                prompts = [
                    {"title": q[:60], "message": q}
                    for q in result["followups"][:3]
                ]
                set_suggested_prompts(prompts=prompts, title="Dig deeper:")
        except Exception as e:
            client.chat_update(
                channel=channel,
                ts=placeholder["ts"],
                text="Something went wrong. Please try again.",
            )

    def _build_blocks(result: dict) -> list[dict]:
        """Build Block Kit blocks with answer and followup action buttons."""
        # Split answer into chunks of 3000 chars (Slack section limit) at line boundaries
        answer = result["answer"]
        blocks = []
        while answer:
            if len(answer) <= 3000:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": answer}})
                break
            # Find last newline before 3000
            cut = answer.rfind("\n", 0, 3000)
            if cut <= 0:
                cut = 3000
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": answer[:cut]}})
            answer = answer[cut:].lstrip("\n")
        if result["followups"]:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": q[:75]},
                            "action_id": f"followup_{i}",
                            "value": q,
                        }
                        for i, q in enumerate(result["followups"][:3])
                    ],
                }
            )
        return blocks

    # Also handle @mentions in channels
    @app.event("app_mention")
    def handle_mention(event, client):
        text = re.sub(r"<@[A-Z0-9]+>\s*", "", event.get("text", "")).strip()
        if not text:
            client.chat_postMessage(
                channel=event["channel"],
                thread_ts=event["ts"],
                text="Ask me a question about the data!",
            )
            return

        # Post a placeholder message as a thinking indicator
        placeholder = client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["ts"],
            text="_Thinking..._",
        )

        try:
            result = ask_llm(text, sheets_client, schema)
            client.chat_update(
                channel=event["channel"],
                ts=placeholder["ts"],
                text=result["answer"],
                blocks=_build_blocks(result),
            )
        except Exception as e:
            client.chat_update(
                channel=event["channel"],
                ts=placeholder["ts"],
                text="Something went wrong. Please try again.",
            )

    @app.event("message")
    def handle_thread_reply(event, client):
        """Handle follow-up replies in channel threads (no @mention needed)."""
        # Only handle thread replies, not top-level messages
        if "thread_ts" not in event or event.get("thread_ts") == event.get("ts"):
            return
        # Ignore bot's own messages
        if event.get("bot_id") or event.get("user") == bot_user_id:
            return
        # Ignore messages that are @mentions (handled by handle_mention)
        if f"<@{bot_user_id}>" in event.get("text", ""):
            return
        # Only respond in threads where the bot has already replied
        try:
            replies = client.conversations_replies(
                channel=event["channel"], ts=event["thread_ts"], limit=50
            )
            bot_in_thread = any(
                msg.get("user") == bot_user_id or msg.get("bot_id")
                for msg in replies.get("messages", [])[1:]  # skip parent
            )
            if not bot_in_thread:
                return
        except Exception:
            return

        text = event.get("text", "").strip()
        if not text:
            return

        placeholder = client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["thread_ts"],
            text="_Thinking..._",
        )

        try:
            history = _get_thread_history(client, event["channel"], event["thread_ts"])
            result = ask_llm(text, sheets_client, schema, history=history)
            client.chat_update(
                channel=event["channel"],
                ts=placeholder["ts"],
                text=result["answer"],
                blocks=_build_blocks(result),
            )
        except Exception as e:
            client.chat_update(
                channel=event["channel"],
                ts=placeholder["ts"],
                text="Something went wrong. Please try again.",
            )

    @app.action(re.compile(r"^followup_\d+$"))
    def handle_followup(ack, body, client):
        ack()
        question = body["actions"][0]["value"]
        thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
        channel = body["channel"]["id"]

        placeholder = client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"_Thinking about: {question}_",
        )

        try:
            history = _get_thread_history(client, channel, thread_ts)
            result = ask_llm(question, sheets_client, schema, history=history)
            client.chat_update(
                channel=channel,
                ts=placeholder["ts"],
                text=result["answer"],
                blocks=_build_blocks(result),
            )
        except Exception as e:
            client.chat_update(
                channel=channel,
                ts=placeholder["ts"],
                text="Something went wrong. Please try again.",
            )

    # Register assistant middleware AFTER channel event handlers so it doesn't swallow them
    app.use(assistant)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("Sheets bot is running...")
    handler.start()


if __name__ == "__main__":
    main()
