import os


DEFAULT_REMOTE_BASE_URL = ""
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_EMBEDDING_API_KEY = ""
DEFAULT_EMBEDDING_BASE_URL = ""


def normalize_openai_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def build_remote_api_config(api_key: str = "", base_url: str = None):
    return {
        "api_key": (api_key or "").strip(),
        "base_url": normalize_openai_base_url(base_url or DEFAULT_REMOTE_BASE_URL),
    }


def get_default_embedding_config(api_key=None, base_url=None, embedding_model=None):
    resolved_model = embedding_model
    if resolved_model is None:
        resolved_model = os.getenv("AUDIOMATE_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL

    resolved_key = api_key
    if resolved_key is None:
        resolved_key = os.getenv("AUDIOMATE_EMBEDDING_API_KEY") or DEFAULT_EMBEDDING_API_KEY

    resolved_base_url = base_url
    if resolved_base_url is None:
        resolved_base_url = os.getenv("AUDIOMATE_EMBEDDING_BASE_URL") or DEFAULT_EMBEDDING_BASE_URL

    config = build_remote_api_config(api_key=resolved_key, base_url=resolved_base_url)
    config["embedding_model"] = (resolved_model or DEFAULT_EMBEDDING_MODEL).strip()
    return config
