import logging

def create_service_logger(scope: str) -> logging.Logger:
    """Create a logger with a specific scope.

    Args:
        scope: Logger scope (e.g., "office", "scheduler", "arena")

    Returns:
        Logger instance with formatted output

    Example:
        logger = create_service_logger("office")
        logger.info("Document processed")
        # Output: [office] INFO: Document processed
    """
    logger = logging.getLogger(scope)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(f'[{scope}] %(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
