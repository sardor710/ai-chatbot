"""Structured and secure logging configuration with sensitive data sanitization."""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Patterns for potential secrets to mask
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key\s*[:=]\s*["\']?)([^"\'\s]+)', re.IGNORECASE),
    re.compile(r'(?i)(api[_-]?hash\s*[:=]\s*["\']?)([^"\'\s]+)', re.IGNORECASE),
    re.compile(r'(?i)(session\s*[:=]\s*["\']?)(1[0-9a-zA-Z\-_=]{20,})', re.IGNORECASE),
    re.compile(r'(?i)(password\s*[:=]\s*["\']?)([^"\'\s]+)', re.IGNORECASE),
    re.compile(r'(?i)(phone\s*[:=]\s*["\']?)(\+?[0-9]{10,15})', re.IGNORECASE),
    re.compile(r"\b[a-zA-Z0-9_-]{32,64}\b"),  # Generic hashes / keys (like api_hash or openAI keys)
]


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive tokens, hashes, and keys from logs."""

    def __init__(self, known_secrets: list[str] | None = None) -> None:
        super().__init__()
        self.known_secrets = [s for s in (known_secrets or []) if s and len(s) > 4]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.sanitize(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.sanitize(str(arg)) for arg in record.args)
        return True

    def sanitize(self, text: str) -> str:
        """Replace known secrets and matching secret patterns with [REDACTED]."""
        if not text:
            return text
        sanitized = text
        for secret in self.known_secrets:
            sanitized = sanitized.replace(secret, "[REDACTED]")
        for pattern in SECRET_PATTERNS:
            # Mask captures or matches
            sanitized = pattern.sub(
                r"\1[REDACTED]" if r"\1" in pattern.pattern else "[REDACTED]", sanitized
            )
        return sanitized


def setup_logging(
    log_level_str: str = "INFO",
    logs_dir: str = "logs",
    known_secrets: list[str] | None = None,
) -> logging.Logger:
    """Set up rotating file handlers and console handler with security sanitization."""
    log_path = Path(logs_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, log_level_str.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers on re-init
    if root_logger.handlers:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sensitive_filter = SensitiveDataFilter(known_secrets=known_secrets)

    # 1. Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    root_logger.addHandler(console_handler)

    # 2. Main App Log (Rotating)
    app_file_handler = RotatingFileHandler(
        filename=log_path / "app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    app_file_handler.setLevel(numeric_level)
    app_file_handler.setFormatter(formatter)
    app_file_handler.addFilter(sensitive_filter)
    root_logger.addHandler(app_file_handler)

    # 3. Error Log (Rotating)
    error_file_handler = RotatingFileHandler(
        filename=log_path / "error.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)
    error_file_handler.addFilter(sensitive_filter)
    root_logger.addHandler(error_file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return root_logger
