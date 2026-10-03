"""Designated legacy audit composition; installation only binds a lazy factory."""
from .legacy_ports import LegacyAuditBindings, configure_legacy_audit_factory


def build_legacy_audit_bindings() -> LegacyAuditBindings:
    # This static import is registered as a bootstrap dependency. Delaying it
    # also allows signal_audit to be imported before the package is initialized.
    from signal_audit import SignalAuditStore, calculate_data_quality
    return LegacyAuditBindings(SignalAuditStore, calculate_data_quality)


def install_legacy_audit_factory() -> None:
    configure_legacy_audit_factory(build_legacy_audit_bindings)
