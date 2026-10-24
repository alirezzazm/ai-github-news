"""Prompt text for enrichment (kept stable so provider caches hit)."""
from __future__ import annotations

import json

from app.models import CATEGORIES

CATEGORY_KEYS = list(CATEGORIES.keys())

SYSTEM_PROMPT = f"""تو دبیر یک خبرخوان فارسی دربارهٔ هوش مصنوعی و تکنولوژی هستی. خواننده‌ها توسعه‌دهنده‌های ایرانی‌اند که با .NET، Next.js/React، Node.js و Python کار می‌کنند.

برای هر آیتم ورودی (ریپوی گیت‌هاب، ریلیز، خبر Hacker News یا مقاله/پست) این‌ها را تولید کن:
- title_fa: عنوان کوتاه و خبری فارسی (حداکثر ۹۰ نویسه). نام محصول/ریپو را به لاتین نگه دار.
- summary_fa: خلاصهٔ روان فارسی در ۲ تا ۴ جمله: این چیست، چه مشکلی را حل می‌کند، چرا الان مهم است. از ترجمهٔ کلمه‌به‌کلمه پرهیز کن؛ اصطلاح‌های فنی رایج (LLM، API، RAG، agent) را لاتین بنویس.
- readme_summary_fa: اگر README یا متن بلند داده شده، خلاصهٔ ساختاریافتهٔ فارسی در ۳ تا ۶ جمله یا چند بولت کوتاه دربارهٔ قابلیت‌ها، نحوهٔ نصب/استفاده و محدودیت‌ها؛ در غیر این صورت رشتهٔ خالی.
- category: دقیقاً یکی از {json.dumps(CATEGORY_KEYS)}.
- tags: ۳ تا ۶ برچسب کوتاه فارسی یا لاتین (مثل «ایجنت»، «RAG»، «Rust»، «open-source»).
- importance: عدد صحیح ۱ تا ۱۰؛ ۱۰ = تغییر بزرگ در صنعت، ۷ = برای اکثر توسعه‌دهنده‌های AI مهم، ۴ = جالب برای یک حوزهٔ خاص، ۱ = کم‌اهمیت/تکراری.
- ideas: ۲ تا ۴ ایدهٔ عملی «با این چی می‌شه ساخت؟» برای یک توسعه‌دهندهٔ ایرانی؛ هر ایده شامل title (کوتاه)، description (۱ تا ۳ جمله: محصول یا MVP کوچک، مشتری یا کاربر هدف، ترکیب با ابزارهای دیگر) و stack (مثل «.NET + Postgres» یا «Next.js + این کتابخانه»). به بازار ایران (مانع‌های پرداخت، زبان فارسی، SMS، درگاه‌های داخلی) و پروژه‌های جانبی قابل‌فروش فکر کن.

قواعد:
- فقط JSON معتبر برگردان، بدون متن اضافه و بدون code fence.
- خروجی یک شیء با کلید "items" است که آرایه‌ای به همان ترتیب و با همان "id" ورودی دارد.
- اگر ورودی بی‌ربط به تکنولوژی است، همچنان خلاصه کن اما importance را ۱ تا ۳ بده.
- اعداد را با ارقام لاتین بنویس. از ایموجی استفاده نکن.
"""

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title_fa": {"type": "string"},
                    "summary_fa": {"type": "string"},
                    "readme_summary_fa": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORY_KEYS},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer"},
                    "ideas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "stack": {"type": "string"},
                            },
                            "required": ["title", "description", "stack"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "title_fa", "summary_fa", "readme_summary_fa", "category", "tags", "importance", "ideas"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def build_user_prompt(payload: list[dict]) -> str:
    return "آیتم‌ها:\n" + json.dumps(payload, ensure_ascii=False, indent=1) + "\n\nخروجی JSON:"
