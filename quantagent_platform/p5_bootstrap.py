"""Compose the P5 storage implementation at the designated package startup."""
from .p5_ports import configure_p5_services
from .p5_storage_services import LocalP5Services


def install_p5_services() -> None:
    """Install a stateless provider; open no files, databases or network connections."""
    configure_p5_services(LocalP5Services())
