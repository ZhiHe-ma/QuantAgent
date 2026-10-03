"""Designated legacy audit composition; installation only binds a lazy factory."""
from .legacy_ports import (LegacyAuditBindings, configure_legacy_audit_factory,
                           configure_legacy_recovery_factory)


def build_legacy_audit_bindings() -> LegacyAuditBindings:
    # This static import is registered as a bootstrap dependency. Delaying it
    # also allows signal_audit to be imported before the package is initialized.
    from signal_audit import SignalAuditStore, calculate_data_quality
    return LegacyAuditBindings(SignalAuditStore, calculate_data_quality)


def install_legacy_audit_factory() -> None:
    configure_legacy_audit_factory(build_legacy_audit_bindings)


def build_legacy_recovery_store(daily_dir: str, *, dry_run: bool = False):
    from .recovery.sqlite_store import SQLiteRecoveryStore
    return SQLiteRecoveryStore(daily_dir, dry_run=dry_run)


def install_legacy_recovery_factory() -> None:
    configure_legacy_recovery_factory(build_legacy_recovery_store)
