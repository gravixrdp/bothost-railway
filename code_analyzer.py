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
    "cancel delete",
    "❌ cancel",
    "🔙 back",
    "❌ cancel delete",
}

# Sub-menu navigation buttons
NAVIGATION_BUTTONS: Set[str] = {
    "back to main menu",
    "main menu",
    "back to my bots",
    "back to admin",
    "back to users",
    "back to all bots",
    "back to bot inspector",
    "back to bot details",
    "back",
    "exit admin",
    "🔙 back to main menu",
    "🏠 main menu",
    "🔙 back to my bots",
    "🔙 back to admin",
    "🔙 back to users",
    "🔙 back to all bots",
    "🏠 back to admin",
    "🔙 back",
    "🏠 exit admin",
}

# Sub-menu action and feature buttons
SUB_MENU_BUTTONS: Set[str] = {
    "refer & earn free slots",
    "refer & earn slots",
    "refer & earn",
    "manage env vars",
    "export data backup",
    "export backup",
    "🎁 refer & earn free slots",
    "🎁 refer & earn slots",
    "🎁 refer & earn",
    "🔑 manage env vars",
    "💾 export data backup",
    "💾 export backup",
} | NAVIGATION_BUTTONS

# Top-level main menu buttons
MAIN_MENU_BUTTONS: Set[str] = {
    "open admin panel",
    "open admin panel 👑",
    "👑 open admin panel",
    "👑 open admin panel 👑",
    "my hosted bots",
    "🤖 my hosted bots",
    "quick templates",
    "quick template deploy",
    "⚡ quick templates",
    "⚡ quick template deploy",
    "my account & slots",
    "📊 my account & slots",
    "help & guidelines",
    "❓ help & guidelines",
    "customer support",
    "💬 customer support",
    "refresh",
    "🔄 refresh",
    "host new bot",
    "➕ host new bot",
    "host another bot",
    "➕ host another bot",
    "refer & earn free slots",
    "refer & earn slots",
    "refer & earn",
    "🎁 refer & earn free slots",
    "🎁 refer & earn slots",
    "🎁 refer & earn",
    "manage env vars",
    "🔑 manage env vars",
    "export data backup",
    "export backup",
    "💾 export data backup",
    "💾 export backup",
}

# Top-level admin menu buttons
ADMIN_MENU_BUTTONS: Set[str] = {
    "system stats",
    "📊 system stats",
    "user manager",
    "👥 user manager",
    "all hosted bots",
    "🤖 all hosted bots",
    "force-sub channels",
    "📢 force-sub channels",
    "broadcast announcement",
    "📢 broadcast announcement",
    "toggle maintenance",
    "⚙️ toggle maintenance",
    "refresh admin",
    "🔄 refresh admin",
    "exit admin",
    "🏠 exit admin",
    "add force-sub channel",
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


# =====================================================================
# Typography & Unicode Font Conversion Engines
# =====================================================================

_TO_BOLD_SANS_MAP: dict[int, int] = {
    ord(c): 0x1D5D4 + (ord(c) - ord("A")) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
}
_TO_BOLD_SANS_MAP.update({
    ord(c): 0x1D5EE + (ord(c) - ord("a")) for c in "abcdefghijklmnopqrstuvwxyz"
})
_TO_BOLD_SANS_MAP.update({
    ord(c): 0x1D7EC + (ord(c) - ord("0")) for c in "0123456789"
})
_TO_BOLD_SANS_TABLE = str.maketrans({k: chr(v) for k, v in _TO_BOLD_SANS_MAP.items()})

_FROM_BOLD_SANS_MAP: dict[int, str] = {}

# Mathematical Sans-Serif Bold (A-Z: U+1D5D4..U+1D5ED, a-z: U+1D5EE..U+1D607, 0-9: U+1D7EC..U+1D7F5)
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _FROM_BOLD_SANS_MAP[0x1D5D4 + i] = c
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _FROM_BOLD_SANS_MAP[0x1D5EE + i] = c
for i, c in enumerate("0123456789"):
    _FROM_BOLD_SANS_MAP[0x1D7EC + i] = c

# Mathematical Bold Serif (A-Z: U+1D400..U+1D419, a-z: U+1D41A..U+1D433, 0-9: U+1D7CE..U+1D7D7)
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _FROM_BOLD_SANS_MAP[0x1D400 + i] = c
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _FROM_BOLD_SANS_MAP[0x1D41A + i] = c
for i, c in enumerate("0123456789"):
    _FROM_BOLD_SANS_MAP[0x1D7CE + i] = c

# Mathematical Sans-Serif Regular
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _FROM_BOLD_SANS_MAP[0x1D5A0 + i] = c
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _FROM_BOLD_SANS_MAP[0x1D5BA + i] = c
for i, c in enumerate("0123456789"):
    _FROM_BOLD_SANS_MAP[0x1D7E2 + i] = c

# Mathematical Sans-Serif Italic
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _FROM_BOLD_SANS_MAP[0x1D608 + i] = c
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _FROM_BOLD_SANS_MAP[0x1D622 + i] = c

# Mathematical Sans-Serif Bold Italic
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _FROM_BOLD_SANS_MAP[0x1D63C + i] = c
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _FROM_BOLD_SANS_MAP[0x1D656 + i] = c

# Mathematical Monospace
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _FROM_BOLD_SANS_MAP[0x1D670 + i] = c
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _FROM_BOLD_SANS_MAP[0x1D68A + i] = c
for i, c in enumerate("0123456789"):
    _FROM_BOLD_SANS_MAP[0x1D7F6 + i] = c

_FROM_BOLD_SANS_TABLE = str.maketrans(_FROM_BOLD_SANS_MAP)


def to_bold_sans(text: str) -> str:
    """
    Converts standard ASCII letters (A-Z, a-z) and numbers (0-9) to Mathematical
    Sans-Serif Bold Unicode (e.g., A -> 𝗔, a -> 𝗮, 0 -> 𝟬).
    Keeps emojis, spaces, and punctuation untouched.

    Args:
        text: Plain ASCII or mixed text string.

    Returns:
        Formatted string with alphanumeric characters converted to Mathematical Sans-Serif Bold.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    return text.translate(_TO_BOLD_SANS_TABLE)


def from_bold_sans(text: str) -> str:
    """
    Converts Mathematical Sans-Serif Bold (and Serif Bold) characters back to standard
    ASCII characters (e.g., 𝗔 -> A, 𝗮 -> a, 𝟬 -> 0).

    Args:
        text: Styled Unicode text string.

    Returns:
        Cleaned ASCII string.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    return text.translate(_FROM_BOLD_SANS_TABLE)


def make_button_text(title: str) -> str:
    """
    Formats reply keyboard button text with elegant ⇋ arrow brackets and bold sans-serif typography.

    Args:
        title: Plain text string for the button label.

    Returns:
        Formatted button text using ⇋ arrows and Mathematical Bold Sans-Serif font:
        e.g., '⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋'
    """
    if not isinstance(title, str) or not title.strip():
        return ""
    clean_title = title.strip()
    return f"⇋ {to_bold_sans(clean_title)} ⇋"


_ARROW_REGEX = re.compile(r"[⇋⇆⇌⇄↔→←\u21cb\u21c6\u21cc\u21c4\u2194\u2192\u2190]")
_EMOJI_SYMBOL_PATTERN = (
    r"[\U00010000-\U0010ffff"
    r"\u200d\ufe0e\ufe0f\u200b-\u200f"
    r"\u20a0-\u20cf\u2100-\u214f\u2190-\u21ff\u2200-\u22ff"
    r"\u2300-\u23ff\u2460-\u24ff\u2500-\u257f\u2580-\u259f"
    r"\u25a0-\u25ff\u2600-\u27bf\u2900-\u297f\u2b00-\u2bff"
    r"\u3000-\u303f"
    r"•·▪▫★☆◆◇▶◀▼▲»«|~*]"
)
_LEADING_EMOJI_SYMBOL_REGEX = re.compile(rf"^(?:\s|{_EMOJI_SYMBOL_PATTERN})+")
_TRAILING_EMOJI_SYMBOL_REGEX = re.compile(rf"(?:\s|{_EMOJI_SYMBOL_PATTERN})+$")


def normalize_user_input(text: str) -> str:
    """
    Normalizes user input by converting Unicode bold/sans fonts to standard ASCII,
    stripping arrow variations (⇋, ⇆, ⇌, ⇄, ↔, →, ←), removing leading and trailing
    emojis and decorative symbols, and collapsing redundant whitespace.

    Args:
        text: Raw user input text.

    Returns:
        Normalized ASCII string.
    """
    if not isinstance(text, str) or not text:
        return ""
    converted = from_bold_sans(text)
    without_arrows = _ARROW_REGEX.sub(" ", converted)
    without_leading = _LEADING_EMOJI_SYMBOL_REGEX.sub("", without_arrows)
    without_trailing = _TRAILING_EMOJI_SYMBOL_REGEX.sub("", without_leading)
    return " ".join(without_trailing.split())


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

    norm = normalize_user_input(text).lower()
    if not norm:
        return False

    if norm in ALL_CANCELLATION_AND_NAV_TEXTS:
        return True

    # Handle dynamic button variants and prefixes
    if norm.startswith("toggle maintenance"):
        return True
    if norm.startswith("cancel delete"):
        return True
    if norm.startswith("cancel"):
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

    norm = normalize_user_input(text).lower()
    if not norm:
        return False

    if norm in MENU_NAVIGATION_BUTTONS:
        return True

    # Handle dynamic button variants and prefixes
    if norm.startswith("toggle maintenance"):
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
    "to_bold_sans",
    "from_bold_sans",
    "make_button_text",
    "normalize_user_input",
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
