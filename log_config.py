import logging
import logging.config
import os


def setup_logging(default_path='logs', default_level=logging.DEBUG):
    """
    Setup logging configuration
    """
    # Create logs directory if it doesn't exist
    if not os.path.exists(default_path):
        os.makedirs(default_path)

    debug_log_file_path = os.path.join(default_path, "debug.log")
    error_log_file_path = os.path.join(default_path, "error.log")
    warning_log_file_path = os.path.join(default_path, "warning.log")
    info_log_file_path = os.path.join(default_path, "info.log")

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "detailed": {
                # Detailed format: Time - Level - [Logger Name] [File:Line] - Message
                "format": "%(asctime)s - %(levelname)s - [%(name)s] [%(filename)s:%(lineno)d] - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",  # Only show INFO and above in console
                "formatter": "detailed",
                "stream": "ext://sys.stdout",
            },
            "debug": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",  # Keep detailed logs in file
                "formatter": "detailed",
                "filename": debug_log_file_path,
                "maxBytes": 10 * 1024 * 1024,  # 10MB per file
                "backupCount": 4,             # Keep 4 backup files
                "encoding": "utf-8",
            },
            "error": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "detailed",
                "filename": error_log_file_path,
                "maxBytes": 10 * 1024 * 1024,  # 10MB per file
                "backupCount": 4,             # Keep 4 backup files
                "encoding": "utf-8",
            },
            "warning": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "WARNING",
                "formatter": "detailed",
                "filename": warning_log_file_path,
                "maxBytes": 10 * 1024 * 1024,  # 10MB per file
                "backupCount": 4,             # Keep 4 backup files
                "encoding": "utf-8",
            },
            "info": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": "detailed",
                "filename": info_log_file_path,
                "maxBytes": 10 * 1024 * 1024,  # 10MB per file
                "backupCount": 4,             # Keep 4 backup files
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "": {  # Root logger configuration
                "handlers": ["console", "debug", "error"],
                "level": default_level,
            },
        },
    }

    # Apply the configuration dictionary
    logging.config.dictConfig(logging_config)

    # Return a logger instance for the caller
    return logging.getLogger("AppRoot")
