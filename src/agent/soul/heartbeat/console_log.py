from __future__ import annotations

import logging

_console_enabled: bool = True


def configure_console_log(enabled: bool) -> None:
    global _console_enabled
    _console_enabled = bool(enabled)


def console_log_enabled() -> bool:
    return _console_enabled


def hb_debug(logger: logging.Logger, msg: str, *args: object) -> None:
    if _console_enabled:
        logger.debug(msg, *args)


def hb_info(logger: logging.Logger, msg: str, *args: object) -> None:
    if _console_enabled:
        logger.info(msg, *args)


def hb_warning(logger: logging.Logger, msg: str, *args: object) -> None:
    if _console_enabled:
        logger.warning(msg, *args)


def hb_error(logger: logging.Logger, msg: str, *args: object) -> None:
    if _console_enabled:
        logger.error(msg, *args)
