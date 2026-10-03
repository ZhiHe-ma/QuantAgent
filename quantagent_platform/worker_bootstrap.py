"""Default worker-service composition, called by the compatibility startup facade."""
from .isolated_runtime import LocalWorkerServices
from .worker_ports import configure_worker_services


def install_worker_services() -> None:
    """Only bind the implementation factory; do not read files or spawn a worker."""
    configure_worker_services(LocalWorkerServices)
