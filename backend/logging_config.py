import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import traceback

from config import settings


class JSONFormatter(logging.Formatter):
    
    def __init__(
        self,
        include_timestamp: bool = True,
        include_level: bool = True,
        include_logger: bool = True,
        include_path: bool = True,
        extra_fields: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_level = include_level
        self.include_logger = include_logger
        self.include_path = include_path
        self.extra_fields = extra_fields or {}
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {}
        
        if self.include_timestamp:
            log_data["timestamp"] = datetime.utcnow().isoformat() + "Z"
        
        if self.include_level:
            log_data["level"] = record.levelname
            log_data["level_num"] = record.levelno
        
        if self.include_logger:
            log_data["logger"] = record.name
        
        if self.include_path:
            log_data["module"] = record.module
            log_data["function"] = record.funcName
            log_data["line"] = record.lineno
        
        log_data["message"] = record.getMessage()
        
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None,
            }
        
        for key, value in record.__dict__.items():
            if key not in [
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'levelno', 'lineno', 'module', 'msecs',
                'pathname', 'process', 'processName', 'relativeCreated',
                'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
                'message', 'taskName'
            ]:
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)
        
        log_data.update(self.extra_fields)
        
        return json.dumps(log_data, default=str)


class ColoredFormatter(logging.Formatter):
    
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[41m',
    }
    RESET = '\033[0m'
    
    def __init__(self, fmt: Optional[str] = None):
        super().__init__(fmt or '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


class LoggerConfig:
    
    def __init__(
        self,
        level: str = "INFO",
        log_file: Optional[str] = None,
        json_logs: bool = False,
        max_file_size: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        console_output: bool = True,
        colored_console: bool = True,
    ):
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.log_file = Path(log_file) if log_file else None
        self.json_logs = json_logs
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.console_output = console_output
        self.colored_console = colored_console


def setup_logging(
    config: Optional[LoggerConfig] = None,
    app_name: str = "weekly_agent",
) -> logging.Logger:
    if config is None:
        config = LoggerConfig(
            level=settings.log_level,
            log_file=settings.log_file,
            json_logs=getattr(settings, 'json_logs', False),
        )
    
    root_logger = logging.getLogger()
    root_logger.setLevel(config.level)
    
    root_logger.handlers.clear()
    
    if config.console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(config.level)
        
        if config.json_logs:
            console_handler.setFormatter(JSONFormatter())
        elif config.colored_console:
            console_handler.setFormatter(ColoredFormatter())
        else:
            console_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
        
        root_logger.addHandler(console_handler)
    
    if config.log_file:
        config.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            config.log_file,
            maxBytes=config.max_file_size,
            backupCount=config.backup_count,
            encoding='utf-8',
        )
        file_handler.setLevel(config.level)
        
        if config.json_logs:
            file_handler.setFormatter(JSONFormatter(
                extra_fields={"app": app_name}
            ))
        else:
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
        
        root_logger.addHandler(file_handler)
    
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    
    logger = logging.getLogger(app_name)
    logger.info(f"Logging configured: level={logging.getLevelName(config.level)}")
    
    return logger


class LogContext:
    
    _context: Dict[str, Any] = {}
    
    def __init__(self, **kwargs):
        self._new_context = kwargs
        self._old_context = {}
    
    def __enter__(self):
        self._old_context = LogContext._context.copy()
        LogContext._context.update(self._new_context)
        return self
    
    def __exit__(self, *args):
        LogContext._context = self._old_context
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls._context.get(key, default)
    
    @classmethod
    def all(cls) -> Dict[str, Any]:
        return cls._context.copy()


class ContextFilter(logging.Filter):
    
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in LogContext.all().items():
            setattr(record, key, value)
        return True


def get_request_logger(request_id: str, user_id: Optional[int] = None) -> logging.Logger:
    logger = logging.getLogger(f"request.{request_id[:8]}")
    
    context_filter = ContextFilter()
    logger.addFilter(context_filter)
    
    LogContext._context = {
        "request_id": request_id,
        "user_id": user_id,
    }
    
    return logger


def log_operation_start(
    logger: logging.Logger,
    operation: str,
    **kwargs
) -> Dict[str, Any]:
    context = {
        "operation": operation,
        "start_time": datetime.utcnow(),
        **kwargs
    }
    
    logger.info(
        f"Starting operation: {operation}",
        extra={"operation_context": context}
    )
    
    return context


def log_operation_end(
    logger: logging.Logger,
    context: Dict[str, Any],
    success: bool = True,
    error: Optional[Exception] = None,
    **kwargs
) -> None:
    duration = (datetime.utcnow() - context["start_time"]).total_seconds()
    operation = context["operation"]
    
    log_data = {
        "operation": operation,
        "duration_seconds": duration,
        "success": success,
        **kwargs
    }
    
    if success:
        logger.info(
            f"Completed operation: {operation} in {duration:.2f}s",
            extra=log_data
        )
    else:
        log_data["error"] = str(error) if error else "Unknown error"
        logger.error(
            f"Failed operation: {operation} after {duration:.2f}s - {error}",
            extra=log_data,
            exc_info=error is not None
        )


def get_audit_logger() -> logging.Logger:
    return logging.getLogger("audit")


def log_audit_event(
    event_type: str,
    user_id: Optional[int] = None,
    resource: Optional[str] = None,
    action: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
):
    audit_logger = get_audit_logger()
    
    audit_data = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "user_id": user_id,
        "resource": resource,
        "action": action,
        "success": success,
        "details": details or {},
    }
    
    if success:
        audit_logger.info(
            f"AUDIT: {event_type} - {action} on {resource}",
            extra=audit_data
        )
    else:
        audit_logger.warning(
            f"AUDIT FAIL: {event_type} - {action} on {resource}",
            extra=audit_data
        )
