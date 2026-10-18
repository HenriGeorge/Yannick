"""
Configuration for NotebookLM Skill
Centralizes constants, selectors, and paths
"""

from pathlib import Path

# Paths
SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
BROWSER_STATE_DIR = DATA_DIR / "browser_state"
BROWSER_PROFILE_DIR = BROWSER_STATE_DIR / "browser_profile"
STATE_FILE = BROWSER_STATE_DIR / "state.json"
AUTH_INFO_FILE = DATA_DIR / "auth_info.json"
LIBRARY_FILE = DATA_DIR / "library.json"

# NotebookLM Selectors
QUERY_INPUT_SELECTORS = [
    # Redesigned "Gemini Notebook" UI (2026) — language-agnostic first
    'textarea[placeholder*="vraag" i]',      # NL "Stel een vraag of maak iets"
    'textarea[placeholder*="question" i]',   # EN
    'textarea[placeholder*="Ask" i]',
    'div[contenteditable="true"]',
    '[role="textbox"]',
    "textarea",                               # generic last-resort
    # Legacy classic UI
    "textarea.query-box-input",
    'textarea[aria-label="Feld für Anfragen"]',
    'textarea[aria-label="Input for queries"]',
]

RESPONSE_SELECTORS = [
    # Redesigned "Gemini Notebook" UI (2026): the answer bubble is .to-user-*.
    # NB: the FROM-user echo uses .message-text-content, so never select that
    # alone or you scrape your own question back. Answer text lives here:
    ".to-user-container .to-user-message-inner-content",
    ".to-user-container labs-tailwind-doc-viewer",
    ".to-user-container",
    # Legacy classic UI
    ".to-user-container .message-text-content",
    "[data-message-author='bot']",
    "[data-message-author='assistant']",
]

# Browser Configuration
BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',  # Patches navigator.webdriver
    '--disable-dev-shm-usage',
    '--no-sandbox',
    '--no-first-run',
    '--no-default-browser-check'
]

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# Timeouts
LOGIN_TIMEOUT_MINUTES = 10
QUERY_TIMEOUT_SECONDS = 120
PAGE_LOAD_TIMEOUT = 30000
