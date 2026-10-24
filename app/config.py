"""Application settings.

Values come from environment variables (or a .env file). A subset can be
overridden at runtime from the admin panel; those overrides live in the
``settings`` table and are read through :func:`app.settings_store.get_setting`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general -----------------------------------------------------------
    site_name: str = "رادار گیت‌هاب"
    site_url: str = "http://localhost:4200"
    timezone: str = "Asia/Tehran"
    log_level: str = "INFO"
    data_dir: str = "./data"

    # --- database ----------------------------------------------------------
    database_url: str = "sqlite:///./data/dev.db"

    # --- admin -------------------------------------------------------------
    secret_key: str = "change-me-please"
    admin_user: str = "admin"
    admin_password: str = "admin"

    # --- github ------------------------------------------------------------
    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    github_trending_languages: str = ",python,typescript,javascript,rust,go,c#,jupyter-notebook"
    github_search_days_new: int = 14
    github_search_min_stars_active: int = 1500
    github_readme_max_chars: int = 4000

    # --- llm ---------------------------------------------------------------
    llm_providers: str = "anthropic,openai"  # order = priority; empty disables LLM
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "low"  # low | medium | high
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_batch_size: int = 4
    llm_daily_item_limit: int = 150
    llm_daily_token_limit: int = 2_000_000
    llm_min_prescore: float = 15.0
    llm_max_output_tokens: int = 6000
    llm_timeout_seconds: int = 180

    # --- notifications -----------------------------------------------------
    notify_provider: str = "bale"  # bale | telegram
    notify_bot_token: str = ""
    notify_chat_id: str = ""
    digest_hour: int = 9
    digest_items: int = 10
    alert_min_importance: int = 9  # 0 disables instant alerts

    # --- scheduler (minutes) ----------------------------------------------
    collect_github_every_min: int = 360
    collect_releases_every_min: int = 180
    collect_hn_every_min: int = 120
    collect_rss_every_min: int = 120
    enrich_every_min: int = 20
    spike_check_every_min: int = 360
    command_poll_seconds: int = 15

    # --- misc --------------------------------------------------------------
    hn_min_points: int = 120
    hn_max_stories: int = 200
    rss_max_items_per_feed: int = 40
    item_retention_days: int = 180

    @property
    def trending_languages(self) -> list[str]:
        return [x.strip() for x in self.github_trending_languages.split(",")]

    @property
    def provider_order(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_providers.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


# Settings keys that the admin panel may override at runtime (stored in DB).
RUNTIME_KEYS: dict[str, dict] = {
    "github_token": {"label": "توکن GitHub (فقط‌خواندنی)", "secret": True},
    "llm_providers": {"label": "ترتیب ارائه‌دهنده‌های LLM (مثلاً anthropic,openai)", "secret": False},
    "anthropic_api_key": {"label": "کلید Anthropic", "secret": True},
    "anthropic_model": {"label": "مدل Anthropic", "secret": False},
    "anthropic_effort": {"label": "effort مدل Anthropic (low/medium/high)", "secret": False},
    "openai_api_key": {"label": "کلید OpenAI‑compatible (OpenAI، OpenRouter، Groq، Ollama…)", "secret": True},
    "openai_base_url": {"label": "Base URL ارائه‌دهندهٔ OpenAI‑compatible", "secret": False},
    "openai_model": {"label": "مدل OpenAI‑compatible", "secret": False},
    "llm_daily_item_limit": {"label": "سقف آیتم‌های روزانه برای LLM", "secret": False},
    "llm_daily_token_limit": {"label": "سقف توکن روزانه (ورودی+خروجی)", "secret": False},
    "llm_batch_size": {"label": "تعداد آیتم در هر درخواست LLM", "secret": False},
    "llm_min_prescore": {"label": "حداقل امتیاز اولیه برای ارسال به LLM", "secret": False},
    "notify_provider": {"label": "سرویس اعلان (bale یا telegram)", "secret": False},
    "notify_bot_token": {"label": "توکن بات بله/تلگرام", "secret": True},
    "notify_chat_id": {"label": "شناسهٔ چت مقصد", "secret": False},
    "digest_hour": {"label": "ساعت ارسال خلاصهٔ روزانه (به وقت تهران)", "secret": False},
    "alert_min_importance": {"label": "حداقل اهمیت برای هشدار فوری (۰ = خاموش)", "secret": False},
    "hn_min_points": {"label": "حداقل امتیاز Hacker News", "secret": False},
    "site_url": {"label": "آدرس عمومی سایت (برای RSS)", "secret": False},
}
