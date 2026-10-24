"""Cross-source linking: detect GitHub repositories referenced by news items."""
from __future__ import annotations

import re

_GH_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:[/?#]|$)")
_SKIP_OWNERS = {"topics", "trending", "features", "marketplace", "orgs", "search", "settings", "sponsors", "about", "login", "explore", "collections", "events", "pulls", "issues", "notifications", "apps", "blog"}


def extract_repo_full_name(url: str | None) -> str:
    """Return 'owner/repo' when the URL points at a GitHub repository, else ''."""
    if not url:
        return ""
    m = _GH_RE.search(url.strip())
    if not m:
        return ""
    owner, repo = m.group(1), m.group(2)
    if owner.lower() in _SKIP_OWNERS:
        return ""
    repo = re.sub(r"\.git$", "", repo)
    return f"{owner}/{repo}"
