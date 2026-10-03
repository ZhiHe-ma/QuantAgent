"""Standalone audit error contract; importing it does not initialize the plugin host."""


class SignalAuditError(RuntimeError):
    """Base error for audit persistence failures."""
