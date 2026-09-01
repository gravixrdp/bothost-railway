"""
Gravix-Host Code Analyzer & AST Engine.

Provides AST-based syntax validation, token extraction, dependency analysis,
and cancellation & menu navigation detection for hosted Telegram bots.
"""

from __future__ import annotations

import ast
import io
import os
import re
import shutil
from typing import List, Optional, Set, Tuple
import zipfile

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

# Sub-menu action and feature buttons
SUB_MENU_BUTTONS: Set[str] = {
    "🎁 refer & earn free slots",
    "🎁 refer & earn",
    "🔑 manage env vars",
    "💾 export data backup",
    "💾 export backup",
} | NAVIGATION_BUTTONS

# Top-level main menu buttons
MAIN_MENU_BUTTONS: Set[str] = {
    "👑 open admin panel",
    "🤖 my hosted bots",
    "⚡ quick template deploy",
    "📊 my account & slots",
    "❓ help & guidelines",
    "💬 customer support",
    "🔄 refresh",
    "➕ host new bot",
    "➕ host another bot",
    "🎁 refer & earn free slots",
    "🎁 refer & earn",
    "🔑 manage env vars",
    "💾 export data backup",
    "💾 export backup",
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
    | SUB_MENU_BUTTONS
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


def extract_bot_token(code_str: str) -> Optional[str]:
    """
    Alias for extract_token_from_code.
    Scans code using regex to extract any hardcoded Telegram bot token.

    Args:
        code_str: Python source code or text.

    Returns:
        Cleaned token string if found, otherwise None.
    """
    return extract_token_from_code(code_str)


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


def extract_and_validate_zip(
    zip_bytes: bytes, target_dir: str
) -> Tuple[bool, str, Optional[str], Optional[List[str]]]:
    """
    Extracts a zip archive into target_dir in memory with security validation
    to prevent zip-slip / directory traversal.
    Locates and flattens main.py if nested, validates Python syntax,
    extracts token and imported module dependencies.

    Args:
        zip_bytes: Raw binary bytes of the uploaded ZIP file.
        target_dir: Absolute path of destination directory to extract to.

    Returns:
        Tuple of (is_valid, message, extracted_token, imported_modules).
        - If success: (True, "Valid Zip Project", extracted_token, imported_modules)
        - If failure: (False, error_message, None, None)
    """
    if not zip_bytes:
        return False, "Missing 'main.py' entry point in root of ZIP archive.", None, None

    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_ref:
            # 1. Security Check: Validate all members against zip-slip / directory traversal
            for member in zip_ref.infolist():
                abs_dest = os.path.abspath(os.path.join(target_dir, member.filename))
                try:
                    if os.path.commonpath([target_dir, abs_dest]) != target_dir:
                        return False, f"Security violation: Zip slip detected in '{member.filename}'.", None, None
                except ValueError:
                    return False, f"Security violation: Invalid path traversal in '{member.filename}'.", None, None

            # 2. Extract all members safely
            zip_ref.extractall(target_dir)
    except zipfile.BadZipFile:
        return False, "Invalid or corrupted ZIP archive.", None, None
    except Exception as e:
        return False, f"Failed to extract ZIP archive: {e}", None, None

    # 3. Locate main.py or flatten single root directory (e.g., repo-main/main.py or mybot/main.py)
    main_py_path = os.path.join(target_dir, "main.py")
    if not os.path.isfile(main_py_path):
        candidate_dirs = [
            d for d in os.listdir(target_dir)
            if os.path.isdir(os.path.join(target_dir, d)) and d not in ("__MACOSX", ".git")
        ]
        for cdir_name in candidate_dirs:
            cdir_path = os.path.join(target_dir, cdir_name)
            if os.path.isfile(os.path.join(cdir_path, "main.py")):
                for item in os.listdir(cdir_path):
                    src = os.path.join(cdir_path, item)
                    dst = os.path.join(target_dir, item)
                    if os.path.exists(dst):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        else:
                            os.remove(dst)
                    shutil.move(src, dst)
                try:
                    os.rmdir(cdir_path)
                except Exception:
                    pass
                break

    main_py_path = os.path.join(target_dir, "main.py")
    if not os.path.isfile(main_py_path):
        return False, "Missing 'main.py' entry point in root of ZIP archive.", None, None

    # 4. Read main.py content and validate syntax
    try:
        with open(main_py_path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    except Exception as e:
        return False, f"Failed to read 'main.py': {e}", None, None

    is_valid, err_msg, line_no, line_text = validate_python_syntax(code)
    if not is_valid:
        if line_no:
            return False, f"Syntax Error in 'main.py' at line {line_no}: {err_msg}", None, None
        return False, f"Syntax Error in 'main.py': {err_msg}", None, None

    # 5. Extract token and imported modules
    extracted_token = extract_bot_token(code)
    imported_modules = extract_imported_modules(code)

    return True, "Valid Zip Project", extracted_token, imported_modules


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
    "extract_bot_token",
    "extract_imported_modules",
    "extract_and_validate_zip",
    "is_cancellation_text",
    "is_menu_navigation_text",
    "CANCELLATION_PHRASES",
    "NAVIGATION_BUTTONS",
    "SUB_MENU_BUTTONS",
    "MAIN_MENU_BUTTONS",
    "ADMIN_MENU_BUTTONS",
    "MENU_NAVIGATION_BUTTONS",
    "ALL_CANCELLATION_AND_NAV_TEXTS",
    "TOKEN_REGEX",
    "TOKEN_PATTERN",
]
