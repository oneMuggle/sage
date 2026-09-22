import logging

from backend.loggers import create_service_logger


def test_create_service_logger_returns_logger():
    logger = create_service_logger("test")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test"

def test_create_service_logger_has_handler():
    logger = create_service_logger("test")
    assert len(logger.handlers) > 0

def test_create_service_logger_reuses_existing():
    logger1 = create_service_logger("test")
    logger2 = create_service_logger("test")
    assert logger1 is logger2  # Same instance
