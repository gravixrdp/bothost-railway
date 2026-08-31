"""
Gravix-Host Code Analyzer & AST Engine.

Provides AST-based syntax validation, token extraction, dependency analysis,
and cancellation & menu navigation detection for hosted Telegram bots.
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional, Set, Tuple

TOKEN_REGEX = r"(\d{6,14}:[a-zA-Z0-9_-]{30,45})"
TOKEN_PATTERN = re.compile(TOKEN_REGEX)

# Standard cancellation words and commands
CANCELLATION_PHRASES: Set[str] = {
    "❌ cancel",
    "cancel",
    "/cancel",
    "exit",
    "/exit",
    "quit",
    "/quit",
    "abort",
    "/abort",
    "stop",
    "/stop",
    "back",
    "/back",
    "🔙 back",
    "❌ cancel delete",
}

# Sub-menu navigation buttons
NAVIGATION_BUTTONS: Set[str] = {
    "🔙 back to main menu",
    "🏠 main menu",
    "🔙 back to my bots",
    "🔙 back to admin",
    "🔙 back to users",
    "🔙 back to all bots",
    "🏠 back to admin",
    "🔙 back",
}

# Top-level main menu buttons
MAIN_MENU_BUTTONS: Set[str] = {
    "👑 open admin panel",
    "🤖 my hosted bots",
    "⚡ quick template deploy",
    "📊 my account & slots",
    "❓ help & guidelines",
    "🔄 refresh",
    "➕ host new bot",
    "➕ host another bot",
}

# Top-level admin menu buttons
ADMIN_MENU_BUTTONS: Set[str] = {
    "📊 system stats",
    "👥 user manager",
    "🤖 all hosted bots",
    "📢 force-sub channels",
    "📢 broadcast announcement",
    "⚙️ toggle maintenance",
    "🔄 refresh admin",
    "🏠 exit admin",
    "➕ add force-sub channel",
}

# Combined set of all top-level menu and navigation buttons
MENU_NAVIGATION_BUTTONS: Set[str] = (
    MAIN_MENU_BUTTONS
    | ADMIN_MENU_BUTTONS
    | NAVIGATION_BUTTONS
)

# Complete set of cancellation and navigation phrases
ALL_CANCELLATION_AND_NAV_TEXTS: Set[str] = (
    CANCELLATION_PHRASES
    | MENU_NAVIGATION_BUTTONS
)


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
    Checks whether a user's input text represents a cancellation command or intent,
    or a navigation/menu button press that should abort the current conversational step.

    Args:
        text: Input string from user message.

    Returns:
        True if the text matches a cancellation phrase or navigation/menu button, False otherwise.
    """
    if not isinstance(text, str):
        return False

    cleaned = text.strip().lower()
    if not cleaned:
        return False

    if cleaned in ALL_CANCELLATION_AND_NAV_TEXTS:
        return True

    # Handle dynamic button variants and prefixes
    if cleaned.startswith("⚙️ toggle maintenance"):
        return True
    if cleaned.startswith("❌ cancel delete"):
        return True
    if cleaned.startswith("❌ cancel"):
        return True

    return False


def is_menu_navigation_text(text: str) -> bool:
    """
    Checks whether a user's input text matches any top-level menu or navigation button.

    Args:
        text: Input string from user message.

    Returns:
        True if the text matches any top-level menu or navigation button, False otherwise.
    """
    if not isinstance(text, str):
        return False

    cleaned = text.strip().lower()
    if not cleaned:
        return False

    if cleaned in MENU_NAVIGATION_BUTTONS:
        return True

    # Handle dynamic button variants and prefixes
    if cleaned.startswith("⚙️ toggle maintenance"):
        return True

    return False


__all__ = [
    "validate_python_syntax",
    "extract_token_from_code",
    "extract_imported_modules",
    "is_cancellation_text",
    "is_menu_navigation_text",
    "CANCELLATION_PHRASES",
    "NAVIGATION_BUTTONS",
    "MAIN_MENU_BUTTONS",
    "ADMIN_MENU_BUTTONS",
    "MENU_NAVIGATION_BUTTONS",
    "ALL_CANCELLATION_AND_NAV_TEXTS",
    "TOKEN_REGEX",
    "TOKEN_PATTERN",
]
