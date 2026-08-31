"""
Gravix-Host Code Analyzer & AST Engine.

Provides AST-based syntax validation, token extraction, dependency analysis,
and cancellation detection for hosted Telegram bots.
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional, Tuple

TOKEN_REGEX = r"(\d{6,14}:[a-zA-Z0-9_-]{30,45})"
TOKEN_PATTERN = re.compile(TOKEN_REGEX)

CANCELLATION_PHRASES = {
    "❌ cancel",
    "cancel",
    "/cancel",
    "back",
    "exit",
    "/exit",
    "/back",
    "🔙 back to main menu",
    "🏠 main menu",
    "🔙 back to admin",
    "🔙 back",
    "❌ cancel delete",
}


def validate_python_syntax(code_str: str) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """
    Validates Python source code syntax using AST parsing.

    Args:
        code_str: The Python source code to validate.

    Returns:
        A tuple of (is_valid, message, line_number, error_line_text).
        - If valid: (True, "Syntax Valid", None, None)
        - If empty/whitespace: (False, "Code cannot be empty.", None, None)
        - If SyntaxError: (False, error_msg, line_number, line_text)
        - If other error: (False, str(e), None, None)
    """
    if not isinstance(code_str, str) or not code_str.strip():
        return False, "Code cannot be empty.", None, None

    try:
        ast.parse(code_str)
        return True, "Syntax Valid", None, None
    except SyntaxError as e:
        msg = str(e.msg) if e.msg is not None else str(e)
        return False, msg, e.lineno, e.text
    except Exception as e:
        return False, str(e), None, None


def extract_token_from_code(code_str: str) -> Optional[str]:
    """
    Scans code using regex to extract any hardcoded Telegram bot token.

    Args:
        code_str: Python source code or text.

    Returns:
        Cleaned token string if found, otherwise None.
    """
    if not isinstance(code_str, str) or not code_str:
        return None

    match = TOKEN_PATTERN.search(code_str)
    if match:
        token = match.group(1).strip().strip("`'\"")
        return token
    return None


def extract_imported_modules(code_str: str) -> List[str]:
    """
    Parses AST and extracts all top-level module names imported via
    `import x` and `from y import z`.

    Args:
        code_str: Python source code.

    Returns:
        Deduplicated list of top-level imported module names in order of appearance.
    """
    if not isinstance(code_str, str) or not code_str.strip():
        return []

    try:
        tree = ast.parse(code_str)
    except Exception:
        return []

    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    top_level = alias.name.split(".")[0].strip()
                    if top_level:
                        modules.append(top_level)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level = node.module.split(".")[0].strip()
                if top_level:
                    modules.append(top_level)

    # Preserve order while deduplicating
    return list(dict.fromkeys(modules))


def is_cancellation_text(text: str) -> bool:
    """
    Checks whether a user's input text represents a cancellation command or intent.

    Args:
        text: Input string from user message.

    Returns:
        True if the text matches a known cancellation phrase, False otherwise.
    """
    if not isinstance(text, str):
        return False
    return text.strip().lower() in CANCELLATION_PHRASES


__all__ = [
    "validate_python_syntax",
    "extract_token_from_code",
    "extract_imported_modules",
    "is_cancellation_text",
    "CANCELLATION_PHRASES",
    "TOKEN_REGEX",
    "TOKEN_PATTERN",
]
