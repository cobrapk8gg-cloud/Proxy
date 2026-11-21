"""Provider names, default routes and shared upstream errors."""

PROVIDER_INFO = {
    "chatgpt": ("ChatGPT", "gpt"),
    "gemini": ("Gemini", "gemini"),
    "deepseek": ("DeepSeek Telegram", "deepseek-telegram"),
    "qwen": ("Qwen", "qwen"),
    "chatgpt_guest": ("ChatGPT Guest", "gpt-guest"),
    "openai_api": ("OpenAI API", "openai-api"),
    "gemini_api": ("Gemini API", "gemini-api"),
}

OFFICIAL_APIS = frozenset(("openai_api", "gemini_api"))
NO_FIXED_CHAT = OFFICIAL_APIS | {"chatgpt_guest"}


class ProviderError(Exception):
    def __init__(self, message, status=502):
        self.message = message
        self.status = status
        super().__init__(message)
