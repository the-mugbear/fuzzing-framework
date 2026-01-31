"""
Dynamic protocol plugin loader
"""
import base64
import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from core.config import settings
from core.models import ProtocolPlugin, TransportProtocol
from core.engine.seed_synthesizer import synthesize_seeds_for_protocol

logger = structlog.get_logger()


class PluginLoadError(Exception):
    """Raised when plugin fails to load"""

    pass


def normalize_seeds_for_json(seeds: List) -> List[str]:
    """
    Convert seed bytes to base64 strings for safe JSON serialization.

    Args:
        seeds: List of seeds (can be bytes or already base64 strings)

    Returns:
        List of base64-encoded strings
    """
    normalized = []
    for seed in seeds:
        if isinstance(seed, bytes):
            # Convert bytes to base64 for JSON serialization
            normalized.append(base64.b64encode(seed).decode('ascii'))
        elif isinstance(seed, str):
            # Already a string (might be base64 or regular string)
            # Try to verify it's valid base64, if not, encode it
            try:
                base64.b64decode(seed)
                normalized.append(seed)
            except Exception:
                # Not base64, encode as UTF-8 bytes then base64
                normalized.append(base64.b64encode(seed.encode()).decode('ascii'))
        else:
            logger.warning("unexpected_seed_type", type=type(seed))
    return normalized


def decode_seeds_from_json(seeds: List[str]) -> List[bytes]:
    """
    Decode base64 seed strings back to bytes.

    Args:
        seeds: List of base64-encoded seed strings

    Returns:
        List of seed bytes
    """
    decoded = []
    for seed in seeds:
        if isinstance(seed, bytes):
            # Already bytes, use as-is
            decoded.append(seed)
        elif isinstance(seed, str):
            # Decode from base64
            try:
                decoded.append(base64.b64decode(seed))
            except Exception as e:
                logger.warning("failed_to_decode_seed", error=str(e))
    return decoded


def normalize_data_model_for_json(data_model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert all bytes in data_model to base64 strings for JSON serialization.

    Args:
        data_model: Protocol data model dictionary

    Returns:
        Data model with bytes converted to base64 strings
    """
    if data_model is None:
        return {}
    def convert_bytes(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode('ascii')
        elif isinstance(obj, dict):
            return {k: convert_bytes(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_bytes(item) for item in obj]
        return obj

    return convert_bytes(data_model)


def denormalize_data_model_from_json(data_model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert base64 strings back to bytes in data_model.

    This is the reverse of normalize_data_model_for_json. Use this before
    passing data_model to ProtocolParser or other components that need raw bytes.

    Args:
        data_model: Protocol data model dictionary with base64-encoded bytes

    Returns:
        Data model with base64 strings converted back to bytes
    """
    if not data_model:
        return {}

    result = data_model.copy()

    # Decode seeds
    if 'seeds' in result and isinstance(result['seeds'], list):
        result['seeds'] = decode_seeds_from_json(result['seeds'])

    # Decode default values in blocks
    if 'blocks' in result:
        new_blocks = []
        for block in result['blocks']:
            new_block = block.copy()
            # Only decode 'default' if the field type is 'bytes'
            if 'default' in new_block and new_block.get('type') == 'bytes':
                if isinstance(new_block['default'], str):
                    try:
                        new_block['default'] = base64.b64decode(new_block['default'])
                    except Exception:
                        pass  # Keep as string if decode fails
            new_blocks.append(new_block)
        result['blocks'] = new_blocks

    return result


class PluginManager:
    """Manages protocol plugin loading and validation"""

    # Subdirectories to scan for plugins (in priority order)
    PLUGIN_SUBDIRS = ["custom", "examples", "standard"]

    def __init__(self, plugins_dir: Optional[Path] = None):
        self.plugins_dir = plugins_dir or settings.plugins_dir
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_plugins: Dict[str, Dict[str, Any]] = {}
        # Map plugin names to their file paths
        self._plugin_paths: Dict[str, Path] = {}

    def discover_plugins(self) -> List[str]:
        """
        Discover all available protocol plugins.

        Scans the main plugins directory and subdirectories:
        - standard/: Production-ready protocol implementations
        - examples/: Learning/tutorial plugins
        - custom/: User-created custom protocols

        Returns:
            List of plugin names (without .py extension)
        """
        plugins = []
        self._plugin_paths.clear()

        # Scan subdirectories first (custom > examples > standard priority)
        for subdir in self.PLUGIN_SUBDIRS:
            subdir_path = self.plugins_dir / subdir
            if subdir_path.exists():
                for plugin_file in subdir_path.glob("*.py"):
                    if plugin_file.name.startswith("_"):
                        continue
                    plugin_name = plugin_file.stem
                    if plugin_name not in self._plugin_paths:
                        self._plugin_paths[plugin_name] = plugin_file
                        plugins.append(plugin_name)

        # Also scan root plugins_dir for backwards compatibility
        for plugin_file in self.plugins_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            plugin_name = plugin_file.stem
            if plugin_name not in self._plugin_paths:
                self._plugin_paths[plugin_name] = plugin_file
                plugins.append(plugin_name)

        return plugins

    def _find_plugin_file(self, plugin_name: str) -> Optional[Path]:
        """
        Find the plugin file by name, checking subdirectories.

        Args:
            plugin_name: Name of the plugin (without .py)

        Returns:
            Path to plugin file, or None if not found
        """
        # Check cached paths first
        if plugin_name in self._plugin_paths:
            return self._plugin_paths[plugin_name]

        # Check subdirectories
        for subdir in self.PLUGIN_SUBDIRS:
            plugin_file = self.plugins_dir / subdir / f"{plugin_name}.py"
            if plugin_file.exists():
                self._plugin_paths[plugin_name] = plugin_file
                return plugin_file

        # Check root directory
        plugin_file = self.plugins_dir / f"{plugin_name}.py"
        if plugin_file.exists():
            self._plugin_paths[plugin_name] = plugin_file
            return plugin_file

        return None

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

        plugin_file = self._find_plugin_file(plugin_name)
        if not plugin_file:
            raise PluginLoadError(f"Plugin not found: {plugin_name}")

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

            data_model = module.data_model
            state_model = module.state_model
            response_model = getattr(module, "response_model", None)
            response_handlers = copy.deepcopy(getattr(module, "response_handlers", []))

            # NEW: Load orchestrated session configuration
            protocol_stack = getattr(module, "protocol_stack", None)
            connection_config = getattr(module, "connection", None)
            heartbeat_config = getattr(module, "heartbeat", None)
            transport_value = getattr(
                module,
                "transport",
                getattr(module, "TRANSPORT", TransportProtocol.TCP.value),
            )
            try:
                transport = (
                    transport_value
                    if isinstance(transport_value, TransportProtocol)
                    else TransportProtocol(str(transport_value).lower())
                )
            except ValueError:
                logger.warning(
                    "invalid_plugin_transport",
                    plugin=plugin_name,
                    transport=transport_value,
                )
                transport = TransportProtocol.TCP

            # Auto-generate seeds if not provided
            if 'seeds' not in data_model or not data_model['seeds']:
                logger.info("auto_generating_seeds", plugin=plugin_name)
                try:
                    synthesized_seeds = synthesize_seeds_for_protocol(data_model, state_model)
                    data_model['seeds'] = synthesized_seeds
                    logger.info(
                        "seeds_auto_generated",
                        plugin=plugin_name,
                        count=len(synthesized_seeds)
                    )
                except Exception as e:
                    logger.warning(
                        "seed_synthesis_failed",
                        plugin=plugin_name,
                        error=str(e)
                    )
                    # Don't fail plugin load if synthesis fails
                    data_model['seeds'] = []

            # Normalize data_model to convert bytes to base64 for JSON safety
            # This must be done before caching/returning
            data_model_json_safe = normalize_data_model_for_json(data_model)

            # Normalize protocol_stack data models if present
            protocol_stack_normalized = None
            if protocol_stack:
                protocol_stack_normalized = self._normalize_protocol_stack(protocol_stack)

            plugin_data = {
                "data_model": data_model_json_safe,  # Base64-encoded for JSON safety
                "state_model": state_model,
                "response_model": normalize_data_model_for_json(response_model) if response_model else None,
                "response_handlers": response_handlers,
                "validate_response": getattr(module, "validate_response", None),
                "description": getattr(module, "__doc__", None),
                "version": getattr(module, "__version__", "1.0.0"),
                "transport": transport,
                # Orchestrated session configuration
                "protocol_stack": protocol_stack_normalized,
                "connection": connection_config,
                "heartbeat": heartbeat_config,
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
            response_model=data.get("response_model"),
            response_handlers=data.get("response_handlers", []),
            description=data.get("description"),
            version=data.get("version", "1.0.0"),
            transport=data.get("transport", TransportProtocol.TCP),
            # Orchestrated session configuration
            protocol_stack=data.get("protocol_stack"),
            connection=data.get("connection"),
            heartbeat=data.get("heartbeat"),
        )

    def get_validator(self, plugin_name: str) -> Optional[Callable]:
        """Get the validate_response function for a plugin"""
        if plugin_name not in self._loaded_plugins:
            self.load_plugin(plugin_name)
        return self._loaded_plugins[plugin_name].get("validate_response")

    def get_protocol_stack(self, plugin_name: str) -> Optional[List[Dict[str, Any]]]:
        """Get the protocol_stack configuration for a plugin (if orchestrated)."""
        if plugin_name not in self._loaded_plugins:
            self.load_plugin(plugin_name)
        return self._loaded_plugins[plugin_name].get("protocol_stack")

    def get_connection_config(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get the connection configuration for a plugin."""
        if plugin_name not in self._loaded_plugins:
            self.load_plugin(plugin_name)
        return self._loaded_plugins[plugin_name].get("connection")

    def get_heartbeat_config(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get the heartbeat configuration for a plugin."""
        if plugin_name not in self._loaded_plugins:
            self.load_plugin(plugin_name)
        return self._loaded_plugins[plugin_name].get("heartbeat")

    def is_orchestrated(self, plugin_name: str) -> bool:
        """Check if a plugin defines a protocol_stack (orchestrated session)."""
        stack = self.get_protocol_stack(plugin_name)
        return stack is not None and len(stack) > 0

    def _normalize_protocol_stack(self, stack: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize protocol_stack by converting bytes to base64 in data_models.

        Args:
            stack: Raw protocol_stack from plugin

        Returns:
            Stack with all data_models normalized for JSON safety
        """
        normalized = []
        for stage in stack:
            stage_copy = copy.deepcopy(stage)

            # Normalize data_model if present
            if 'data_model' in stage_copy:
                stage_copy['data_model'] = normalize_data_model_for_json(
                    stage_copy['data_model']
                )

            # Normalize response_model if present
            if 'response_model' in stage_copy:
                stage_copy['response_model'] = normalize_data_model_for_json(
                    stage_copy['response_model']
                )

            normalized.append(stage_copy)

        return normalized

    def reload_plugin(self, plugin_name: str) -> ProtocolPlugin:
        """Reload a plugin (useful for development)"""
        if plugin_name in self._loaded_plugins:
            del self._loaded_plugins[plugin_name]
        if plugin_name in sys.modules:
            del sys.modules[plugin_name]
        return self.load_plugin(plugin_name)


# Global plugin manager instance
plugin_manager = PluginManager()
