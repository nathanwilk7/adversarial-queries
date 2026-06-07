import os
import sys

from loguru import logger as logger_init

from constants import USE_LOGGER


class NoOpLogger:
    @staticmethod
    def debug(*args, **kwargs):
        pass

    @staticmethod
    def info(*args, **kwargs):
        pass

    @staticmethod
    def warning(*args, **kwargs):
        pass

    @staticmethod
    def error(*args, **kwargs):
        pass

    @staticmethod
    def opt(*args, **kwargs):
        return NoOpLogger()


if USE_LOGGER:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    logger_init.remove()
    logger_init.add(
        sys.stdout,
        level=os.getenv("LOG_LEVEL") or "WARNING",
        backtrace=True,
        diagnose=True,
        format="<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
    )
    l = logger_init
else:
    l = NoOpLogger()
