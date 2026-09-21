from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import DataPacket


class PluginError(RuntimeError):
    """A plugin could not safely or correctly complete its step."""


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    capability: str
    input_contracts: tuple[str, ...]
    output_contract: str
    permissions: frozenset[str]
    network_access: bool = False
    retry_safe: bool = False
    runtime: str = "in_process"
    catalog_status: str = "verified"

    def validate(self) -> None:
        if not self.plugin_id or not self.version or not self.capability:
            raise PluginError("plugin manifest identity, version and capability are required")
        if not self.output_contract:
            raise PluginError(f"{self.plugin_id}: output_contract is required")
        if self.catalog_status not in {"verified", "experimental", "unverified", "disabled"}:
            raise PluginError(f"{self.plugin_id}: invalid catalog status {self.catalog_status}")


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Any
    allowed_read_roots: tuple[Any, ...]
    allowed_write_roots: tuple[Any, ...]
    offline: bool

    def assert_read_path(self, value: str) -> Any:
        from pathlib import Path

        path = Path(value).expanduser().resolve()
        for root in self.allowed_read_roots:
            try:
                path.relative_to(Path(root).resolve())
                return path
            except ValueError:
                continue
        roots = ", ".join(str(Path(root)) for root in self.allowed_read_roots)
        raise PluginError(f"read path is outside allowed roots: {path}; allowed={roots}")

    def assert_write_path(self, value: str) -> Any:
        from pathlib import Path

        path = Path(value).expanduser().resolve()
        for root in self.allowed_write_roots:
            try:
                path.relative_to(Path(root).resolve())
                return path
            except ValueError:
                continue
        roots = ", ".join(str(Path(root)) for root in self.allowed_write_roots)
        raise PluginError(f"write path is outside allowed roots: {path}; allowed={roots}")


class Plugin(Protocol):
    manifest: PluginManifest

    def run(
        self,
        context: RunContext,
        packet: DataPacket | None,
        config: dict[str, Any],
    ) -> DataPacket:
        ...


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        plugin.manifest.validate()
        plugin_id = plugin.manifest.plugin_id
        if plugin_id in self._plugins:
            raise PluginError(f"duplicate plugin id: {plugin_id}")
        self._plugins[plugin_id] = plugin

    def get(self, plugin_id: str) -> Plugin:
        try:
            plugin = self._plugins[plugin_id]
        except KeyError as exc:
            raise PluginError(f"plugin is not installed or allow-listed: {plugin_id}") from exc
        if plugin.manifest.catalog_status == "disabled":
            raise PluginError(f"plugin is disabled: {plugin_id}")
        return plugin

    def catalog(self) -> list[dict[str, Any]]:
        rows = []
        for plugin_id in sorted(self._plugins):
            manifest = self._plugins[plugin_id].manifest
            rows.append({
                "plugin_id": manifest.plugin_id,
                "version": manifest.version,
                "capability": manifest.capability,
                "input_contracts": list(manifest.input_contracts),
                "output_contract": manifest.output_contract,
                "permissions": sorted(manifest.permissions),
                "network_access": manifest.network_access,
                "retry_safe": manifest.retry_safe,
                "runtime": manifest.runtime,
                "status": manifest.catalog_status,
            })
        return rows
