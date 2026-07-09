import json
import socket
from urllib import error, request


class OpenAICompatibleClient:
    """Small helper for OpenAI-compatible provider metadata endpoints."""

    @staticmethod
    def fetch_available_models(api_key: str, base_url: str):
        base = (base_url or "").strip().rstrip("/")
        key = (api_key or "").strip()
        if not base or not key:
            return {"ok": False, "models": [], "error": "Missing API Key or Base URL"}

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        candidates = [f"{base}/models"] if base.endswith("/v1") else [f"{base}/v1/models", f"{base}/models"]
        urls = []
        seen = set()
        for candidate in candidates:
            normalized = candidate.rstrip("/")
            if normalized and normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)

        last_error = ""
        for url in urls:
            for _attempt in range(2):
                try:
                    req = request.Request(url=url, headers=headers, method="GET")
                    with request.urlopen(req, timeout=30) as resp:
                        raw = resp.read().decode("utf-8", errors="replace")
                    if not raw.strip():
                        last_error = f"{url}: empty response"
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        snippet = raw.strip()[:120].replace("\n", " ")
                        last_error = f"{url}: non-JSON response: {snippet}"
                        break
                    models = []
                    items = data.get("data") or data.get("models") or []
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                model_id = item.get("id") or item.get("name") or ""
                                if model_id:
                                    models.append(str(model_id))
                            elif isinstance(item, str) and item:
                                models.append(item)
                    return {"ok": True, "models": sorted(set(models)), "error": ""}
                except socket.timeout:
                    last_error = f"{url}: request timed out"
                    continue
                except error.HTTPError as http_err:
                    try:
                        raw = http_err.read().decode("utf-8")
                        body = json.loads(raw) if raw else {}
                        msg = body.get("message") or body.get("error") or str(http_err)
                    except Exception:
                        msg = str(http_err)
                    last_error = f"{url}: {msg}"
                    break
                except Exception as exc:
                    reason = getattr(exc, "reason", None)
                    if isinstance(reason, socket.timeout) or "timed out" in str(exc).lower():
                        last_error = f"{url}: request timed out"
                        continue
                    last_error = f"{url}: {exc}"
                    break

        return {"ok": False, "models": [], "error": last_error or "Failed to fetch model list"}
