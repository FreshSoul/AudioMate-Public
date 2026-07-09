from src.utils.secure_storage import delete_secret, get_secret, set_secret


class AuthSession:
    """Small wrapper around secure storage for local model credentials."""

    API_KEY_KEY = "audiomate_api_key"
    BASE_URL_KEY = "audiomate_base_url"

    def set_api_key(self, api_key: str) -> str:
        return set_secret(self.API_KEY_KEY, api_key or "")

    def get_api_key(self):
        return get_secret(self.API_KEY_KEY)

    def set_base_url(self, base_url: str) -> None:
        set_secret(self.BASE_URL_KEY, base_url or "")

    def get_base_url(self):
        return get_secret(self.BASE_URL_KEY)

    def is_logged_in(self) -> bool:
        return False

    def logout(self) -> None:
        for key in (self.API_KEY_KEY, self.BASE_URL_KEY):
            delete_secret(key)
