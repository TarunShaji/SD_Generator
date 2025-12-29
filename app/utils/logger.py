"""
Structured logging utility for the Structured Data Automation Tool.
Provides detailed, structured logs with trace IDs for debugging.
"""
import uuid
import logging
import structlog
from contextvars import ContextVar
from typing import Any, Dict, Optional
from functools import wraps

from app.config import config

# Context variable for trace ID
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """Get current trace ID or generate new one."""
    trace_id = trace_id_var.get()
    if not trace_id:
        trace_id = str(uuid.uuid4())[:8]
        trace_id_var.set(trace_id)
    return trace_id


def set_trace_id(trace_id: Optional[str] = None) -> str:
    """Set a new trace ID for the current context."""
    new_trace_id = trace_id or str(uuid.uuid4())[:8]
    trace_id_var.set(new_trace_id)
    return new_trace_id


def add_trace_id(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Processor to add trace ID to all log entries."""
    event_dict["trace_id"] = get_trace_id()
    return event_dict


def configure_logging():
    """Configure structlog with appropriate processors."""
    processors = [
        structlog.contextvars.merge_contextvars,
        add_trace_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if config.LOG_FORMAT == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.LOG_LEVEL.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a logger instance with the given name."""
    return structlog.get_logger(name)


class LayerLogger:
    """
    Specialized logger for the three-layer architecture.
    Ensures consistent logging format across all layers.
    """
    
    def __init__(self, layer_name: str):
        self.layer_name = layer_name
        self.logger = get_logger(layer_name)
    
    def log_decision(
        self, 
        decision: str, 
        reason: str, 
        url: Optional[str] = None,
        **extra
    ):
        """Log a decision made by this layer."""
        self.logger.info(
            "decision_made",
            layer=self.layer_name,
            decision=decision,
            reason=reason,
            url=url,
            **extra
        )
    
    def log_action(
        self, 
        action: str, 
        status: str = "started",
        **extra
    ):
        """Log an action being performed."""
        self.logger.info(
            f"action_{status}",
            layer=self.layer_name,
            action=action,
            **extra
        )
    
    def log_fallback(
        self, 
        from_source: str, 
        to_source: str, 
        reason: str,
        **extra
    ):
        """Log a fallback from one source to another."""
        self.logger.warning(
            "fallback_triggered",
            layer=self.layer_name,
            from_source=from_source,
            to_source=to_source,
            reason=reason,
            **extra
        )
    
    def log_error(
        self, 
        error: str, 
        error_type: str = "unknown",
        **extra
    ):
        """Log an error with full context."""
        self.logger.error(
            "error_occurred",
            layer=self.layer_name,
            error=error,
            error_type=error_type,
            **extra
        )
    
    def log_http_probe(
        self, 
        url: str, 
        endpoint: str, 
        status_code: Optional[int], 
        result: str,
        **extra
    ):
        """Log an HTTP probe result (used in CMS detection)."""
        self.logger.info(
            "http_probe",
            layer=self.layer_name,
            url=url,
            endpoint=endpoint,
            status_code=status_code,
            result=result,
            **extra
        )
    
    def log_normalization(
        self, 
        source: str, 
        fields_present: list, 
        fields_missing: list,
        confidence: float,
        **extra
    ):
        """Log content normalization details."""
        self.logger.info(
            "content_normalized",
            layer=self.layer_name,
            source=source,
            fields_present=fields_present,
            fields_missing=fields_missing,
            confidence_score=confidence,
            **extra
        )


# Initialize logging on module import
configure_logging()
