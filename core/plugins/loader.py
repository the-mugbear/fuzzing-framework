"""
Dynamic protocol plugin loader
"""
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from core.config import settings
from core.models import ProtocolPlugin

logger = structlog.get_logger()


class PluginLoadError(Exception):
    """Raised when plugin fails to load"""

    pass


class PluginManager:
    """Manages protocol plugin loading and validation"""

    def __init__(self, plugins_dir: Optional[Path] = None):
        self.plugins_dir = plugins_dir or settings.plugins_dir
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_plugins: Dict[str, Dict[str, Any]] = {}

    def discover_plugins(self) -> List[str]:
        """Discover all available protocol plugins"""
        plugins = []
        for plugin_file in self.plugins_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            plugin_name = plugin_file.stem
            plugins.append(plugin_name)
        return plugins

    def load_plugin(self, plugin_name: str) -> ProtocolPlugin:
        """
        Load a protocol plugin by name

        Args:
            plugin_name: Name of the plugin file (without .py)

        Returns:
            ProtocolPlugin instance

        Raises:
            PluginLoadError: If plugin cannot be loaded or is invalid
        """
        # Check cache
        if plugin_name in self._loaded_plugins:
            return self._create_protocol_plugin(plugin_name, self._loaded_plugins[plugin_name])

        plugin_file = self.plugins_dir / f"{plugin_name}.py"
        if not plugin_file.exists():
            raise PluginLoadError(f"Plugin file not found: {plugin_file}")

        logger.info("loading_plugin", plugin=plugin_name, path=str(plugin_file))

        try:
            # Load module dynamically
            spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
            if spec is None or spec.loader is None:
                raise PluginLoadError(f"Could not create module spec for {plugin_file}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_name] = module
            spec.loader.exec_module(module)

            # Validate required attributes
            if not hasattr(module, "data_model"):
                raise PluginLoadError(f"Plugin {plugin_name} missing 'data_model'")
            if not hasattr(module, "state_model"):
                raise PluginLoadError(f"Plugin {plugin_name} missing 'state_model'")

            plugin_data = {
                "data_model": module.data_model,
                "state_model": module.state_model,
                "validate_response": getattr(module, "validate_response", None),
                "description": getattr(module, "__doc__", None),
                "version": getattr(module, "__version__", "1.0.0"),
            }

            # Cache the loaded plugin
            self._loaded_plugins[plugin_name] = plugin_data

            logger.info("plugin_loaded", plugin=plugin_name)
            return self._create_protocol_plugin(plugin_name, plugin_data)

        except Exception as e:
            logger.error("plugin_load_failed", plugin=plugin_name, error=str(e))
            raise PluginLoadError(f"Failed to load plugin {plugin_name}: {e}")

    def _create_protocol_plugin(self, name: str, data: Dict[str, Any]) -> ProtocolPlugin:
        """Create ProtocolPlugin model from loaded data"""
        return ProtocolPlugin(
            name=name,
            data_model=data["data_model"],
            state_model=data["state_model"],
            description=data.get("description"),
            version=data.get("version", "1.0.0"),
        )

    def get_validator(self, plugin_name: str) -> Optional[Callable]:
        """Get the validate_response function for a plugin"""
        if plugin_name not in self._loaded_plugins:
            self.load_plugin(plugin_name)
        return self._loaded_plugins[plugin_name].get("validate_response")

    def reload_plugin(self, plugin_name: str) -> ProtocolPlugin:
        """Reload a plugin (useful for development)"""
        if plugin_name in self._loaded_plugins:
            del self._loaded_plugins[plugin_name]
        if plugin_name in sys.modules:
            del sys.modules[plugin_name]
        return self.load_plugin(plugin_name)


# Global plugin manager instance
plugin_manager = PluginManager()
