"""Constants, commands, and pattern matchers for anonymous bots like @anonrubot."""

import re

CMD_SEARCH = "/search"
CMD_NEXT = "/next"
CMD_STOP = "/stop"
CMD_ENOUGH = "/enough"

# Bot system message patterns in Russian
# Connection notice: only when a partner is actually found and connected
BOT_CONNECT_PATTERNS = [
    re.compile(r"собеседник найден", re.IGNORECASE),
    re.compile(r"партн[её]р найден", re.IGNORECASE),
    re.compile(r"вы подключились к диалогу", re.IGNORECASE),
    re.compile(r"диалог начат", re.IGNORECASE),
]

# Alias for backwards compatibility
BOT_SEARCH_PATTERNS = BOT_CONNECT_PATTERNS

BOT_DISCONNECT_PATTERNS = [
    re.compile(r"собеседник завершил", re.IGNORECASE),
    re.compile(r"собеседник закончил", re.IGNORECASE),
    re.compile(r"диалог заверш[её]н", re.IGNORECASE),
    re.compile(r"собеседник покинул", re.IGNORECASE),
    re.compile(r"вы завершили диалог", re.IGNORECASE),
    re.compile(r"собеседник закончил с вами связь", re.IGNORECASE),
    re.compile(r"напишите /search чтобы искать собеседника", re.IGNORECASE),
    re.compile(r"напишите /search чтобы найти следующего", re.IGNORECASE),
    re.compile(r"напишите /search", re.IGNORECASE),
    re.compile(r"/search чтобы искать собеседника", re.IGNORECASE),
    re.compile(r"/search чтобы найти", re.IGNORECASE),
    re.compile(r"связь прервана", re.IGNORECASE),
    re.compile(r"собеседник отключился", re.IGNORECASE),
]

# Service/status messages from the bot (intermediate search status, feedback prompts, ratings, etc.)
BOT_SERVICE_PATTERNS = [
    re.compile(r"ищ(?:у|ем)\s+собеседника", re.IGNORECASE),
    re.compile(r"поиск собеседника", re.IGNORECASE),
    re.compile(r"у вас уже есть собеседник", re.IGNORECASE),
    re.compile(r"/next\s*[-—]\s*искать", re.IGNORECASE),
    re.compile(r"мнение о .*?собеседнике", re.IGNORECASE),
    re.compile(r"оставьте мнение", re.IGNORECASE),
    re.compile(r"оцените собеседника", re.IGNORECASE),
    re.compile(r"оцените", re.IGNORECASE),
    re.compile(r"остановить поиск", re.IGNORECASE),
    re.compile(r"правила общения", re.IGNORECASE),
    re.compile(r"нарушает правила", re.IGNORECASE),
    re.compile(r"отправить .*?жалоб", re.IGNORECASE),
    re.compile(r"не можете отправлять сообщения", re.IGNORECASE),
    re.compile(r"пожалуйста, подождите", re.IGNORECASE),
    re.compile(r"помогу тебе .*?не бот", re.IGNORECASE | re.DOTALL),
]


def is_bot_connection_notice(text: str) -> bool:
    """Check if message is a bot system message announcing a partner is connected."""
    if not text:
        return False
    return any(p.search(text) for p in BOT_CONNECT_PATTERNS)


def is_bot_disconnection_notice(text: str) -> bool:
    """Check if message is a bot system message announcing chat termination."""
    if not text:
        return False
    return any(p.search(text) for p in BOT_DISCONNECT_PATTERNS)


def is_bot_service_notice(text: str) -> bool:
    """Check if message is a bot intermediate/service message (search status, feedback prompt, etc.)."""
    if not text:
        return False
    return any(p.search(text) for p in BOT_SERVICE_PATTERNS)
