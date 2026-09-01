import os
import re
import html
import logging
import httpx
from typing import Optional, Dict, Any

from config import GROQ_API_KEY, GROQ_MODEL, DATA_DIR
import database
from bot_manager import bot_manager

logger = logging.getLogger("GravixHost.AIDiagnostics")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are Gravix-Host AI Diagnostics Engineer, an elite Python Telegram bot debugger and cloud architect.\n"
    "Your goal is to inspect Python Telegram bot crash logs, tracebacks, and source code, and tell the user and administrator EXACTLY what went wrong and how to fix it.\n\n"
    "Language & Tone Rules:\n"
    "1. Always respond in fluent, professional, and clear ENGLISH only.\n"
    "2. Format your response strictly using Telegram-supported HTML tags (<b>, <i>, <code>, <blockquote>, <pre>).\n"
    "3. Do NOT output markdown symbols (like **, ```, or # headings).\n"
    "4. Do NOT output full HTML document tags (<html>, <head>, <body>, <style>).\n\n"
    "Response Structure:\n"
    "🔍 <b>Root Cause:</b>\n"
    "<blockquote>Clear and concise explanation in English detailing what failed and identifying the specific line or dependency.</blockquote>\n\n"
    "🛠️ <b>How to Fix:</b>\n"
    "<blockquote>Step-by-step resolution instructions.</blockquote>\n\n"
    "💻 <b>Fixed Code Solution:</b>\n"
    "<pre><code># Corrected python code or configuration fix</code></pre>"
)

async def run_groq_ai_diagnostics(bot_id: str, caller_user_id: int, is_admin_caller: bool = False) -> str:
    """
    Analyzes bot error logs, tracebacks, and source code using Groq AI.
    Returns a structured Telegram HTML diagnostics report.
    """
    bot_id = str(bot_id).strip()
    bot_data = database.get_bot(bot_id)
    if not bot_data:
        return f"<blockquote>❌ Bot <code>#{html.escape(bot_id)}</code> not found in database.</blockquote>"

    bot_name = bot_data.get('bot_name', 'Unnamed Bot')
    owner_id = bot_data.get('user_id')
    status = bot_data.get('status', 'STOPPED')

    # 1. Fetch recent logs
    logs = bot_manager.get_logs(bot_id, lines=40)
    if not logs or "No console logs recorded" in logs:
        logs = "No console logs recorded on disk yet."

    # 2. Fetch script code snippet if available
    script_path = bot_data.get('script_path') or os.path.join(DATA_DIR, "bots", f"{owner_id}_{bot_id}", "main.py")
    code_snippet = ""
    if os.path.exists(script_path) and os.path.isfile(script_path):
        try:
            with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
                full_code = f.read()
                code_lines = full_code.splitlines()[:120]
                code_snippet = "\n".join(code_lines)
        except Exception as e:
            code_snippet = f"# Error reading script: {e}"

    # 3. Check if API key is configured
    api_key = GROQ_API_KEY
    if not api_key or api_key == "DISABLED":
        return (
            "<b>🤖 AI INSTANT DIAGNOSTICS ENGINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>⚠️ <b>Groq AI API Key Not Configured.</b>\n"
            "Please configure <code>GROQ_API_KEY</code> in environment variables to enable instant AI error diagnostics.</blockquote>"
        )

    # 4. Prepare User Prompt
    user_content = (
        f"Bot Name: {bot_name}\n"
        f"Bot ID: {bot_id}\n"
        f"Instance Status: {status}\n"
        f"Owner UID: {owner_id}\n\n"
        f"--- CONSOLE LOGS & TRACEBACK ---\n"
        f"{logs}\n\n"
    )
    if code_snippet:
        user_content += (
            f"--- BOT SOURCE CODE (main.py) ---\n"
            f"{code_snippet}\n"
        )

    # 5. Call Groq API
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.15,
                    "max_tokens": 700
                }
            )

            if response.status_code != 200:
                logger.error(f"Groq API returned error {response.status_code}: {response.text}")
                return (
                    f"<b>🤖 AI DIAGNOSTICS [<code>#{html.escape(bot_id)}</code>]</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"<blockquote>⚠️ <b>AI Diagnostics Notice:</b>\n"
                    f"Groq API returned status code <code>{response.status_code}</code>.</blockquote>"
                )

            data = response.json()
            ai_reply = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            ai_reply = ai_reply.replace("```python", "").replace("```html", "").replace("```", "")

            header = (
                f"<b>🤖 AI CRASH DIAGNOSTICS & FIX</b>\n"
                f"<i>Powered by Groq Ultra-Fast AI Engine</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 <b>Bot:</b> <b>{html.escape(bot_name)}</b> (<code>#{html.escape(bot_id)}</code>)\n"
                f"⚡ <b>Status:</b> <code>{status}</code>\n"
                f"👤 <b>Owner:</b> <code>{owner_id}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            return header + ai_reply

    except httpx.TimeoutException:
        return (
            f"<b>🤖 AI DIAGNOSTICS [<code>#{html.escape(bot_id)}</code>]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>⏱️ <b>Request Timeout:</b> The AI diagnostic engine took too long to respond.</blockquote>"
        )
    except Exception as e:
        logger.error(f"Failed to execute AI diagnostics: {e}")
        return (
            f"<b>🤖 AI DIAGNOSTICS [<code>#{html.escape(bot_id)}</code>]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<blockquote>❌ <b>Diagnostic Error:</b> <code>{html.escape(str(e))}</code></blockquote>"
        )
