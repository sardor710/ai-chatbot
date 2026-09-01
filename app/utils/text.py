"""Text processing, extraction and gender classification helpers."""

import re

# Regex patterns
USERNAME_PATTERN = re.compile(r"(?:@|(?:https?://)?t\.me/)([a-zA-Z0-9_]{4,32})", re.IGNORECASE)
AGE_PATTERN = re.compile(
    r"(?:^|[^\d])(1[0-9]|[2-9][0-9])\s*(?:лет|года|год|y\.?o\.?|yo)?(?=[^\d]|$)",
    re.IGNORECASE,
)

# Distinct Russian/English gender tokens
MALE_KEYWORDS = {
    "м",
    "m",
    "парень",
    "пацан",
    "парнишка",
    "кун",
    "мужчина",
    "мальчик",
    "мужской",
    "мужик",
    "парни",
    "чел",
    "male",
    "guy",
    "boy",
    "man",
}
FEMALE_KEYWORDS = {
    "д",
    "ж",
    "f",
    "w",
    "девушка",
    "девочка",
    "тян",
    "женщина",
    "женский",
    "девчонка",
    "дама",
    "девушки",
    "дева",
    "female",
    "girl",
    "woman",
}


FEMALE_NAMES = {
    "аделина", "адель", "александра", "алена", "алёна", "алина", "алиса", "алла", "альбина",
    "амалия", "анастасия", "ангелина", "анжела", "анжелика", "анна", "антонина", "аня", "ася",
    "богдана", "валентина", "валерия", "валя", "василиса", "вася", "вероника", "вера",
    "вика", "виктория", "виолетта", "вита", "владислава", "влада", "галина", "галя",
    "дана", "дарья", "даша", "диаша", "диана", "дина", "ева", "евгения", "екатерина", "елена",
    "елизавета", "жанна", "злата", "зоя", "илона", "инна", "ира", "ирина",
    "карина", "каролина", "катя", "катюша", "кира", "клара", "клава", "кристина", "ксюша", "ксения",
    "лада", "лариса", "лена", "лера", "лида", "лидия", "лиза", "лилия", "лиля", "люба",
    "любовь", "люда", "людмила", "майя", "маргарита", "марина", "мария", "марья", "маша",
    "мила", "милана", "милена", "мирослава", "надя", "надежда", "настя", "наташа", "наталья", "наталия",
    "нелли", "ника", "нина", "оксана", "олеся", "ольга", "оля", "полина", "поля", "рада",
    "раиса", "рената", "рита", "роза", "руслана", "света", "светлана", "снежана", "соня",
    "софия", "софья", "стелла", "стефания", "таисия", "тая", "тамара", "таня", "татьяна",
    "тома", "тоня", "ульяна", "фаина", "эвелина", "элеонора", "элиза", "элина", "элла",
    "эльвира", "эмилия", "эмма", "юлиана", "юлия", "юля", "яна", "ярослава",
}

MALE_NAMES = {
    "александр", "алексей", "алёша", "алеша", "леша", "лёша", "анатолий", "толя", "андрей",
    "антон", "арсений", "сеня", "артем", "артём", "артемий", "артур", "богдан", "борис", "боря",
    "вадим", "валентин", "валерий", "валера", "василий", "вася", "виктор", "витя", "виталий",
    "виталик", "влад", "владимир", "вова", "володя", "владислав", "владлен", "всеволод", "вячеслав",
    "геннадий", "гена", "георгий", "жора", "глеб", "григорий", "гриша", "даниил",
    "данил", "данила", "денис", "демид", "дмитрий", "дима", "евгений", "егор", "захар",
    "иван", "ваня", "игорь", "илья", "кирилл", "константин", "костя", "лев", "лёва",
    "леонид", "леня", "лёня", "максим", "макс", "марк", "матвей", "михаил", "миша", "мирон",
    "никита", "николай", "коля", "олег", "павел", "паша", "петр", "пётр", "петя", "платон",
    "родион", "роман", "рома", "ростислав", "руслан", "семен", "семён", "сергей",
    "серёжа", "сережа", "станислав", "стас", "степан", "стёпа", "степа", "тимофей", "тима",
    "тимур", "федор", "фёдор", "федя", "филипп", "эдуард", "юрий", "юра", "ярослав", "ярик",
}


def clean_text(text: str | None) -> str:
    """Normalize text whitespace and strip leading/trailing spaces."""
    if not text:
        return ""
    # Strip zero-width and control characters
    text = re.sub(r"[\u200b-\u200f\uFEFF]", "", text)
    return " ".join(text.split()).strip()


def extract_telegram_username(text: str) -> str | None:
    """Extract a Telegram username or t.me link from text if present."""
    if not text:
        return None
    match = USERNAME_PATTERN.search(text)
    if match:
        username = match.group(1)
        # Avoid false positives like common words if no @ was used
        if "@" in text or "t.me" in text:
            return f"@{username}"
    return None


def detect_gender_from_response(text: str) -> str | None:
    """
    Detect whether the user answered Male ('M'), Female ('F'), or Unclear (None).
    Handles answers like:
    - 'м', 'д', 'ж', 'f', 'm'
    - 'привет М', 'привет Д 20', 'привет д'
    - 'д19', 'м18', 'д 20', 'м 21'
    - Russian names: 'Кира', 'Вика', 'Влад', 'я Кира', 'меня зовут Влад'
    - words ('девушка', 'парень', 'я тян', etc.)
    - search phrases ('ищу девушку', 'ищу парня')
    """
    if not text:
        return None

    cleaned = clean_text(text).lower()

    # Search phrases: someone saying "ищу девушку / ищу д / ищу тян" is looking for female (i.e. male sender)
    if re.search(r"\bищу\b.*?\b(?:д|ж|девушк\w*|девочк\w*|тян|женщин\w*)\b", cleaned):
        return "M"
    if re.search(r"\bищу\b.*?\b(?:м|парн\w*|пацан\w*|кун|мужчин\w*)\b", cleaned):
        return "F"

    # Attached letter + age or standalone gender letter (e.g. "д19", "м18", "привет д 20", "привет м")
    # Female patterns: standalone 'д' / 'ж' / 'f' or attached to digits like 'д19'
    female_letter_match = re.search(
        r"(?:^|[^\wа-яё])([джdf])(?:\s*[-–—]?\s*\d{1,2})?(?=[^\wа-яё]|$)",
        cleaned,
        re.IGNORECASE,
    )
    # Male patterns: standalone 'м' / 'm' or attached to digits like 'м18'
    male_letter_match = re.search(
        r"(?:^|[^\wа-яё])([мm])(?:\s*[-–—]?\s*\d{1,2})?(?=[^\wа-яё]|$)",
        cleaned,
        re.IGNORECASE,
    )

    # Token matches
    words = re.findall(r"\b[а-яёa-z]+\b", cleaned)

    has_male_word = any(w in MALE_KEYWORDS for w in words)
    has_female_word = any(w in FEMALE_KEYWORDS for w in words)

    # Name matches
    has_male_name = any(w in MALE_NAMES for w in words)
    has_female_name = any(w in FEMALE_NAMES for w in words)

    is_male = has_male_word or has_male_name
    is_female = has_female_word or has_female_name

    if is_female and not is_male:
        return "F"
    if is_male and not is_female:
        return "M"

    # If not resolved by whole words/names, check regex letter matches (like д19, м18)
    if female_letter_match and not male_letter_match:
        return "F"
    if male_letter_match and not female_letter_match:
        return "M"

    return None


def extract_name(text: str) -> str | None:
    """Extract recognized personal name from text if present (e.g. 'Кира', 'я Влад', 'Вика, 19')."""
    if not text:
        return None
    cleaned = clean_text(text).lower()

    # Check direct patterns first: "меня зовут Кира", "зовут Кира", "я Кира"
    intro_match = re.search(r"\b(?:меня\s+зовут|зовут|я)\s+([а-яёa-z]+)\b", cleaned)
    if intro_match:
        cand = intro_match.group(1)
        if cand in FEMALE_NAMES or cand in MALE_NAMES:
            return cand.capitalize()

    # Search words for any recognized name
    words = re.findall(r"\b[а-яёa-z]+\b", cleaned)
    for w in words:
        if w in FEMALE_NAMES or w in MALE_NAMES:
            return w.capitalize()

    return None


def extract_age(text: str) -> int | None:
    """Extract age if mentioned in text (e.g. 'мне 20', 'д 19', 'д19', 'привет Д 20')."""
    if not text:
        return None
    match = AGE_PATTERN.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def match_owner_age(partner_age: int) -> int:
    """
    Determine owner's age to naturally match the female participant's age:
    - If partner is 16-17: 18 (safe adult age).
    - If partner is 18-24: 1 year older (e.g. 18 -> 19, 19 -> 20, 20 -> 21, 23 -> 24).
    - If partner is 25+: same age.
    """
    if partner_age < 18:
        return 18
    elif partner_age <= 24:
        return partner_age + 1
    else:
        return partner_age


GREETING_TOKENS = {
    "привет",
    "приветик",
    "хай",
    "ку",
    "хей",
    "салам",
    "салам алейкум",
    "здравствуй",
    "здравствуйте",
    "здарова",
    "здорово",
    "добрый день",
    "добрый вечер",
    "доброе утро",
    "hello",
    "hi",
    "hey",
    "йоу",
}


def is_greeting_only(text: str) -> bool:
    """Check if the text is purely a greeting without gender or other content."""
    if not text:
        return False
    cleaned = clean_text(text).lower()
    # Strip common trailing punctuation and emojis like ')'
    stripped = re.sub(r"[.,!?;:)\s]+$", "", cleaned).strip()
    return stripped in GREETING_TOKENS


GENDER_QUESTION_PATTERNS = [
    re.compile(r"^\s*м[\s\.,/\\-]*[дж]\b", re.IGNORECASE),
    re.compile(r"\bм\s+или\s+[дж]\b", re.IGNORECASE),
    re.compile(r"\b[дж]\s+или\s+м\b", re.IGNORECASE),
    re.compile(r"\b(?:твой\s+)?пол\??\s*$", re.IGNORECASE),
    re.compile(r"\bты\s+(?:кто|парень|девушка|дева)\b", re.IGNORECASE),
    re.compile(r"\bпарень\s+или\s+девушк\w*\b", re.IGNORECASE),
    re.compile(r"\bдевушк\w*\s+или\s+парень\b", re.IGNORECASE),
]


def is_asking_for_gender(text: str) -> bool:
    """Check if the participant is asking for our gender (e.g. 'мд', 'м или д', 'пол?')."""
    if not text:
        return False
    cleaned = clean_text(text).lower()
    return any(p.search(cleaned) for p in GENDER_QUESTION_PATTERNS)


def contains_sensitive_secrets(text: str, forbidden_secrets: list[str]) -> bool:
    """Check if the text contains any forbidden private strings or tokens."""
    if not text:
        return False
    lower_text = text.lower()
    for secret in forbidden_secrets:
        if secret and len(secret) > 4 and secret.lower() in lower_text:
            return True
    return False


def split_into_messages(text: str, max_messages: int = 3) -> list[str]:
    """
    Split text into short, natural individual messenger bubbles:
    - Splits by explicit newlines first.
    - If a single line contains multiple sentences/clauses, splits them into separate messages.
    - Caps at max_messages (default 3) to prevent flood.
    """
    if not text:
        return []

    # 1. Split by explicit newlines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > 1:
        return lines[:max_messages]

    single = text.strip()

    # 2. Split on sentence boundaries without variable-width look-behind
    # Matches (.!? or closing parens )) followed by space and a capitalized letter or Russian conjunction
    tokens = re.split(
        r"([.!?]+|\)+)\s+(?=[А-ЯЁA-Z]|\b(?:а|и|но|как|что|где|куда|чем|ты|вы)\b)",
        single,
        flags=re.IGNORECASE,
    )
    if len(tokens) > 1:
        parts = []
        i = 0
        while i < len(tokens):
            chunk = tokens[i].strip()
            if i + 1 < len(tokens):
                delim = tokens[i + 1].strip()
                if delim:
                    chunk += delim
                i += 2
            else:
                i += 1
            if chunk:
                parts.append(chunk)
        if 1 < len(parts) <= max_messages:
            return parts

    return [single]
