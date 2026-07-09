from waapi import WaapiClient, CannotConnectToWaapiException
import json
import socket
import os
import time
from urllib.parse import urlparse

from src.waapi.payload_validation import (
    normalize_object_set_args,
    remap_uri_alias,
    sanitize_args,
    sanitize_return_fields,
    sanitize_transform,
    sanitize_waql,
    validate_waapi_payload,
    validate_required_object_args,
)

try:
    from autobahn.websocket.protocol import WebSocketClientFactory as _WebSocketClientFactory
except Exception:
    _WebSocketClientFactory = None


def _patch_websocket_handshake_timeout(min_timeout_seconds: float = 15.0):
    if _WebSocketClientFactory is None:
        return

    patched_flag = getattr(_WebSocketClientFactory, "_audiomate_timeout_patched", False)
    if patched_flag:
        return

    original = _WebSocketClientFactory.setProtocolOptions

    def _patched(self, *args, **kwargs):
        current_timeout = kwargs.get("openHandshakeTimeout")
        if current_timeout is None or float(current_timeout) < float(min_timeout_seconds):
            kwargs["openHandshakeTimeout"] = float(min_timeout_seconds)
        return original(self, *args, **kwargs)

    _WebSocketClientFactory.setProtocolOptions = _patched
    _WebSocketClientFactory._audiomate_timeout_patched = True


_patch_websocket_handshake_timeout()

class _SafeWaapiResult(dict):
    """Dict subclass that catches integer-key access (e.g. result[0])
    with a clear error instead of a confusing KeyError: 0."""

    def __getitem__(self, key):
        if isinstance(key, int):
            hint = "call() returns a dict, not a list."
            if "return" in self:
                hint += " Use result['return'] to get the list of items."
            raise TypeError(
                f"WAAPI call() returned a dict, but you indexed it with [{key}] "
                f"as if it were a list. {hint}"
            )
        return super().__getitem__(key)


class WwiseClient:
    def __init__(self, url="ws://127.0.0.1:8080/waapi"):
        self.url = url
        self.client = None
        self.connected = False
        self.has_changes = False

    def reset_changes(self):
        self.has_changes = False

    def _port_reachable(self, timeout=2):
        """Quick TCP probe to check if WAAPI port is open."""
        try:
            parsed = urlparse(self.url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8080
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False
    
    def connect(self):
        if not self._port_reachable():
            self.client = None
            self.connected = False
            print("Could not connect to Wwise. Is it running?")
            return False

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self.client = WaapiClient(url=self.url)
                self.connected = True
                self._has_source_control_api = None  # reset capability cache
                print(f"Connected to Wwise at {self.url}")
                return True
            except CannotConnectToWaapiException:
                self.client = None
                self.connected = False
                if attempt < max_attempts:
                    print(f"WAAPI connect attempt {attempt}/{max_attempts} timed out, retrying...")
                    time.sleep(2)
                    continue
                print("Could not connect to Wwise. Is it running?")
                return False
            except Exception as e:
                self.client = None
                self.connected = False
                message = str(e)
                if "opening handshake timeout" in message.lower() and attempt < max_attempts:
                    print(f"WAAPI handshake timed out on attempt {attempt}/{max_attempts}, retrying...")
                    time.sleep(2)
                    continue
                print(f"Error connecting to Wwise: {e}")
                return False

    def disconnect(self):
        if self.client:
            self.client.disconnect()
            self.connected = False

    def get_wwise_info(self):
        """Get Wwise version and global info."""
        if not self.connected:
            return None
        try:
            result = self.client.call("ak.wwise.core.getInfo")
            return result
        except Exception as e:
            print(f"Error getting Wwise info: {e}")
            return None

    def get_wwise_version(self):
        """Get Wwise version as a tuple (year, major, minor, build) and version string."""
        info = self.get_wwise_info()
        if info and 'version' in info:
            v = info['version']
            year = v.get('year', 0)
            major = v.get('major', 0)
            minor = v.get('minor', 0)
            build = v.get('build', 0)
            display = v.get('displayName', f"{year}.{major}.{minor}")
            return {
                'year': year,
                'major': major,
                'minor': minor,
                'build': build,
                'display': display,
                'is_2025_or_later': year >= 2025
            }
        return None

    def get_project_info(self):
        if not self.connected:
            return {"error": "Not connected to Wwise."}
        
        try:
            # Get project info
            args = {
                "from": {"ofType": ["Project"]}
            }
            options = {
                "return": ["name", "filePath", "id"]
            }
            result = self.client.call("ak.wwise.core.object.get", args, options=options)
            return result
        except Exception as e:
            return {"error": f"Error getting project info: {e}"}

    def get_project_path(self):
        result = self.get_project_info()
        if not isinstance(result, dict):
            return ""
        items = result.get("return", [])
        if not items:
            return ""
        return (items[0].get("filePath") or "").strip()

    def get_project_directory(self):
        project_path = self.get_project_path()
        return os.path.dirname(project_path) if project_path else ""

    def get_selected_objects(self):
        if not self.connected:
            return _SafeWaapiResult({"error": "Not connected to Wwise.", "objects": []})
        
        try:
            options = {
                "return": ["name", "type", "id", "path", "notes", "pluginName", "shortid", "classid", "@Volume", "@Pitch"]
            }
            # Use self.call to get logging and error handling
            result = self.call("ak.wwise.ui.getSelectedObjects", options=options)
            if not isinstance(result, dict):
                return _SafeWaapiResult({"error": "Unexpected result from ak.wwise.ui.getSelectedObjects.", "objects": []})

            if "objects" in result and isinstance(result.get("objects"), list):
                return result

            selected_objects = result.get("return", []) if isinstance(result.get("return"), list) else []
            normalized = dict(result)
            normalized["objects"] = selected_objects
            return _SafeWaapiResult(normalized)
        except Exception as e:
            return _SafeWaapiResult({"error": f"Error getting selected objects: {e}", "objects": []})

    def list_source_files(self, filter_mode="all", folder="", recursive=True, return_fields=None):
        if not self.connected:
            return []
        # Check if this API exists (not available in all Wwise versions)
        if not hasattr(self, '_has_source_control_api'):
            funcs = self.get_functions()
            self._has_source_control_api = "ak.wwise.core.sourceControl.getSourceFiles" in funcs
        if not self._has_source_control_api:
            return []
        args = {
            "filter": filter_mode,
            "recursive": bool(recursive),
        }
        if folder:
            args["folder"] = folder
        options = {
            "return": return_fields or ["Path", "FileId", "Db"]
        }
        result = self.call("ak.wwise.core.sourceControl.getSourceFiles", args=args, options=options)
        if isinstance(result, dict):
            return result.get("return", [])
        return []

    def call(self, uri, args=None, options=None):
        """
        Direct wrapper for client.call to be used by the AI.
        """
        if not self.connected:
            return _SafeWaapiResult({"error": "Not connected to Wwise."})
            
        uri, old_uri = remap_uri_alias(uri)
        if old_uri:
            print(f"WAAPI Fix: Remapped URI '{old_uri}' -> '{uri}'")
        
        # Track potential changes
        # Heuristic: Assume write unless it matches known read patterns
        uri_lower = uri.lower()
        is_read_op = (
            "get" in uri.split(".")[-1].lower() or  # e.g. object.get, getProperty, getSelectedObjects
            "profiler" in uri_lower or
            "transport" in uri_lower or
            "query" in uri_lower or
            uri_lower.endswith(".get")
        )
        
        # Special handling for UI commands (check if it's just a selection/find command)
        if uri == "ak.wwise.ui.commands.execute" and args:
            command = args.get("command", "")
            if "FindInProjectExplorer" in command or "Inspect" in command:
                is_read_op = True

        try:
            # Sanitize GUID values – LLM sometimes wraps GUIDs in extra quotes
            if args is not None:
                args = sanitize_args(args)
                args = sanitize_transform(args)
                # Fix broken WAQL for selected-object queries
                if isinstance(args.get("waql"), str):
                    args["waql"] = sanitize_waql(args["waql"])
                # Guard against empty string values in critical arguments
                err_msg = validate_required_object_args(args)
                if err_msg:
                    print(f"WAAPI Guard: {err_msg}")
                    return _SafeWaapiResult({"error": err_msg})
                # Auto-fix flat structure for object.set:
                # LLM often sends {"object": "GUID", "@RTPC": [...]}
                # instead of correct {"objects": [{"object": "GUID", ...}]}
                args = normalize_object_set_args(uri, args)
                payload_error = validate_waapi_payload(uri, args, options)
                if payload_error:
                    print(f"WAAPI Guard: {payload_error}")
                    return _SafeWaapiResult({"error": payload_error})
            print(f"WAAPI Call: {uri}\nArgs: {json.dumps(args, indent=2)}\nOptions: {json.dumps(options, indent=2)}")
            # Sanitize options.return fields before sending
            if isinstance(options, dict) and isinstance(options.get("return"), list):
                options["return"] = sanitize_return_fields(options["return"])
                payload_error = validate_waapi_payload(uri, args, options)
                if payload_error:
                    print(f"WAAPI Guard: {payload_error}")
                    return _SafeWaapiResult({"error": payload_error})
            if isinstance(args, dict):
                if options is not None:
                    res = self.client.call(uri, args, options=options)
                else:
                    res = self.client.call(uri, args)
            else:
                if options is not None:
                    res = self.client.call(uri, options=options)
                else:
                    res = self.client.call(uri)
            result = res if res is not None else {}
            # Detect silently failed operations: some WAMP errors cause the
            # underlying waapi library to return None instead of raising.
            # For operations that MUST return data (create, copy, import),
            # treat empty result as an error so error-detection picks it up.
            if res is None:
                action_word = uri.split(".")[-1].lower()
                if any(kw in action_word for kw in ("create", "copy", "import")):
                    err_msg = (
                        f"WAAPI Error: '{uri}' returned no result — the operation "
                        "likely failed. Check Wwise logs for details."
                    )
                    print(err_msg)
                    return _SafeWaapiResult({"error": err_msg})
            # Wrap in safe dict to prevent KeyError/AttributeError from LLM code
            if isinstance(result, dict):
                result = _SafeWaapiResult(result)
            elif not isinstance(result, dict):
                # Underlying library returned a non-dict (e.g. string) — normalize
                result = _SafeWaapiResult({"_raw": result})
            if not is_read_op and not result.get("error"):
                self.has_changes = True
            return result
        except Exception as e:
            print(f"WAAPI Error: {e}")
            return _SafeWaapiResult({"error": str(e)})

    def get_functions(self):
        """
        Returns a list of all available WAAPI functions.
        """
        if not self.connected:
            return []
        try:
            result = self.client.call("ak.wwise.waapi.getFunctions")
            return result.get("functions", [])
        except Exception as e:
            print(f"Error getting functions: {e}")
            return []

    def get_schema(self, uri, include_examples=False):
        """
        Returns the JSON schema for a specific WAAPI function or topic.
        """
        if not self.connected:
            return {}
        try:
            args = {"uri": uri, "includeExamples": bool(include_examples)}
            result = self.client.call("ak.wwise.waapi.getSchema", args)
            return result
        except Exception as e:
            print(f"Error getting schema for {uri}: {e}")
            return {}

    def get_property(self, object_id, property_name):
        """
        Helper to get a single property value (e.g., 'Volume', 'Pitch').
        Returns None if failed or not found.
        """
        if not self.connected: return None
        try:
            # WAAPI uses '@' prefix for properties in return options (e.g. '@Volume')
            # Handle cases where 'property:' might be passed by mistake
            clean_name = property_name.replace("property:", "")
            if not clean_name.startswith("@"):
                prop_key = f"@{clean_name}"
            else:
                prop_key = clean_name
            
            args = {"from": {"id": [object_id]}}
            options = {"return": [prop_key]}
            
            result = self.client.call("ak.wwise.core.object.get", args, options=options)
            
            # Handle response structure: {'return': [...]}
            items = result.get("return", []) if result else []
            
            if items and len(items) > 0:
                # WAAPI returns the key exactly as requested (e.g. '@Volume')
                val = items[0].get(prop_key)
                if val is None:
                    # Fallback: try without @ just in case
                    val = items[0].get(clean_name)
                return val
            return None
        except Exception as e:
            print(f"Error getting property {property_name}: {e}")
            return None

    def set_property(self, object_id, property_name, value):
        """
        Helper to set a single property value.
        """
        if not self.connected: return False
        try:
            # Strip '@' prefix if present, as setProperty expects the clean name
            clean_name = property_name.replace("@", "")
            
            args = {
                "object": object_id,
                "property": clean_name,
                "value": value
            }
            self.client.call("ak.wwise.core.object.setProperty", args)
            self.has_changes = True
            return True
        except Exception as e:
            print(f"Error setting property {property_name}: {e}")
            return False

    def begin_undo_group(self):
        if not self.connected: return False
        try:
            self.client.call("ak.wwise.core.undo.beginGroup")
            return True
        except Exception: return False

    def end_undo_group(self, group_name="Agent Operation"):
        if not self.connected: return False
        try:
            self.client.call("ak.wwise.core.undo.endGroup", {"displayName": group_name})
            return True
        except Exception as e:
            print(f"Warning: end_undo_group failed (likely no matching beginGroup): {e}")
            return False

    def undo(self):
        if not self.connected: return False
        try:
            self.client.call("ak.wwise.core.undo.undo")
            return True
        except Exception: return False


    def search_functions(self, query):
        """
        Search for functions containing the query string (case-insensitive).
        """
        funcs = self.get_functions()
        return [f for f in funcs if query.lower() in f.lower()]
