import logging
from logging.handlers import RotatingFileHandler
from config import get_settings


def get_logger():
    logger = logging.getLogger('procureflow')
    if not logger.handlers:
        settings = get_settings()
        log_dir = settings.require_persistent_path(settings.logs_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / 'app.log', maxBytes=2_000_000,
                                      backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
