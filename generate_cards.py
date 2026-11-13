#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from html import escape
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CARDS_DIR = ROOT / "cards"
FONT_DIR = ROOT / "assets" / "fonts"
CONFIG_PATH = DATA_DIR / "profile.json"
CACHE_PATH = DATA_DIR / "github_stats.json"
CONTRIB_PATH = DATA_DIR / "contributions.json"

API_ROOT = "https://api.github.com"
PUBLIC_CONTRIB = "https://github.com/users/{username}/contributions"

DISPLAY = "Syne, 'Arial Black', 'Helvetica Neue', Arial, sans-serif"
SERIF = "'Cormorant Garamond', Didot, 'Bodoni MT', Georgia, serif"
MONO = "'JetBrains Mono', Consolas, 'Courier New', monospace"
BODY = "'Plus Jakarta Sans', 'Segoe UI', Helvetica, Arial, sans-serif"

FONT_FACES = [
    ("Syne", "syne-800.woff2", 800, "normal"),
    ("Cormorant Garamond", "cormorant-italic-400.woff2", 400, "italic"),
    ("JetBrains Mono", "jetbrains-mono-400.woff2", 400, "normal"),
    ("Plus Jakarta Sans", "jakarta-400.woff2", 400, "normal"),
]

DEFAULT_THEME = {
    "background": "#070708",
    "surface": "#0C0C0E",
    "border": "#FFFFFF14",
    "title": "#F5F5F7",
    "text": "#929292",
    "muted": "#929292",
    "accent": "#D4E836",
}

ANIMATE = True

ANIMATION_CSS = """
@media (prefers-reduced-motion: no-preference){
.rise,.fade{opacity:0;animation:svgFade .9s cubic-bezier(.16,1,.3,1) both}
.rise{animation-name:svgRise}
.grow{transform:scaleX(0);transform-box:fill-box;transform-origin:left center;animation:svgGrow 1s cubic-bezier(.16,1,.3,1) both}
.growY{transform:scaleY(0);transform-box:fill-box;transform-origin:center bottom;animation:svgGrowY 1s cubic-bezier(.16,1,.3,1) both}
@keyframes svgRise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes svgFade{to{opacity:1}}
@keyframes svgGrow{to{transform:scaleX(1)}}
@keyframes svgGrowY{to{transform:scaleY(1)}}
.d1{animation-delay:.06s}.d2{animation-delay:.12s}.d3{animation-delay:.18s}.d4{animation-delay:.24s}
.d5{animation-delay:.30s}.d6{animation-delay:.36s}.d7{animation-delay:.42s}.d8{animation-delay:.48s}
.d9{animation-delay:.54s}.d10{animation-delay:.60s}.d11{animation-delay:.66s}.d12{animation-delay:.72s}
}
@media (prefers-reduced-motion: reduce){
.rise,.fade,.grow,.growY{animation:none!important;opacity:1!important;transform:none!important}
}
"""

CONTRIBUTIONS_QUERY = """
query Contributions($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def load_json(path: Path, default=None):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def anim(*names: str):
    return " ".join(names) if ANIMATE else None


def class_attr(value: str | None) -> str:
    return f' class="{value}"' if value else ""


def format_number(value) -> str:
    number = int(value or 0)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(number)


def month_year(value) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    return parsed.strftime("%b %Y").upper()


def short_date(value) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    return parsed.strftime("%d %b %Y").upper()


def short_day(value) -> str:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    return parsed.strftime("%d %b").upper()


def clean_url(value: str) -> str:
    return str(value).replace("https://", "").replace("http://", "").rstrip("/")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


@lru_cache(maxsize=None)
def font_payload(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_style() -> str:
    faces = []
    for family, filename, weight, style in FONT_FACES:
        path = FONT_DIR / filename
        if not path.is_file():
            continue
        faces.append(
            "@font-face{font-family:'%s';src:url('data:font/woff2;base64,%s') "
            "format('woff2');font-weight:%s;font-style:%s;font-display:swap}"
            % (family, font_payload(path), weight, style)
        )
    if ANIMATE:
        faces.append(ANIMATION_CSS)
    return "<style>%s</style>" % "".join(faces) if faces else ""


@lru_cache(maxsize=32)
def image_uri(path_str: str) -> str | None:
    path = Path(path_str)
    if not path.is_file():
        return None
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def text_tag(
    x,
    y,
    value,
    *,
    size,
    fill,
    family=DISPLAY,
    weight=400,
    anchor=None,
    spacing=None,
    italic=False,
    opacity=None,
    stroke=None,
    stroke_width=None,
    css_class=None,
) -> str:
    attrs = [
        f'x="{x}"',
        f'y="{y}"',
        f'font-family="{family}"',
        f'font-size="{size}"',
        f'fill="{fill}"',
    ]
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if spacing is not None:
        attrs.append(f'letter-spacing="{spacing}"')
    if italic:
        attrs.append('font-style="italic"')
    if opacity is not None:
        attrs.append(f'opacity="{opacity}"')
    if stroke:
        attrs.append(f'stroke="{stroke}"')
        attrs.append(f'stroke-width="{stroke_width or 1}"')
    if css_class:
        attrs.append(f'class="{css_class}"')
    return f"<text {' '.join(attrs)}>{escape(str(value))}</text>"


def mixed_text(
    x,
    y,
    value,
    *,
    size,
    fill,
    family=DISPLAY,
    weight=400,
    spacing=None,
    css_class=None,
    digit_family=MONO,
) -> str:
    attrs = [
        f'x="{x}"',
        f'y="{y}"',
        f'font-family="{family}"',
        f'font-size="{size}"',
        f'fill="{fill}"',
    ]
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if spacing is not None:
        attrs.append(f'letter-spacing="{spacing}"')
    if css_class:
        attrs.append(f'class="{css_class}"')
    spans = []
    for part in re.split(r"(\d+)", str(value)):
        if not part:
            continue
        if part.isdigit():
            spans.append(
                f'<tspan font-family="{digit_family}" font-weight="400">{escape(part)}</tspan>'
            )
        else:
            spans.append(f"<tspan>{escape(part)}</tspan>")
    return f"<text {' '.join(attrs)}>{''.join(spans)}</text>"


def rect(x, y, width, height, fill, stroke=None, radius=0, opacity=None, css_class=None) -> str:
    attrs = [
        f'x="{x}"',
        f'y="{y}"',
        f'width="{width}"',
        f'height="{height}"',
        f'fill="{fill}"',
    ]
    if radius:
        attrs.append(f'rx="{radius}"')
    if stroke:
        attrs.append(f'stroke="{stroke}"')
    if opacity is not None:
        attrs.append(f'opacity="{opacity}"')
    if css_class:
        attrs.append(f'class="{css_class}"')
    return f"<rect {' '.join(attrs)}/>"


def image_tag(x, y, width, height, uri, clip_id, css_class=None) -> str:
    return (
        f'<image x="{x}" y="{y}" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{clip_id})" '
        f'href="{uri}"{class_attr(css_class)}/>'
    )


def svg_header(width: int, height: int, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" fill="none" role="img" '
        f'aria-label="{escape(label, quote=True)}">'
        f"<title>{escape(label)}</title>"
        + build_style()
    )


def frame(width: int, height: int, theme: dict) -> str:
    return (
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="4" '
        f'fill="{theme["background"]}" stroke="{theme["border"]}"/>'
    )


def accent_mark(x: float, y: float, theme: dict, size: int = 6, css_class=None) -> str:
    return rect(x, y, size, size, theme["accent"], css_class=css_class)


def section_label(x: float, y: float, index: str, label: str, theme: dict, css_class=None) -> str:
    return (
        accent_mark(x, y - 6, theme, css_class=css_class)
        + text_tag(
            x + 14,
            y,
            f"( {index} ) \u2014 {label.upper()}",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            spacing=2.2,
            css_class=css_class,
        )
    )


def wrap_text(value: str, max_width: float, size: float, factor: float = 0.52, spacing: float = 0.0, max_lines: int | None = None):
    char_width = size * factor + spacing
    limit = max(1, int(max_width / char_width))
    lines: list[str] = []
    current = ""
    for word in str(value).split():
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(". ") + "..."
    return lines or [str(value)]


def month_keys(today: date, count: int = 12) -> list[str]:
    keys: list[str] = []
    year, month = today.year, today.month
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(keys))


def month_label(key: str) -> str:
    try:
        return datetime.strptime(key, "%Y-%m").strftime("%b").upper()
    except ValueError:
        return key


def level_for_count(count: int, max_count: int) -> int:
    if count <= 0:
        return 0
    if max_count <= 1:
        return 4
    ratio = count / max_count
    if ratio <= 0.25:
        return 1
    if ratio <= 0.5:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


def github_session(token: str | None) -> requests.Session:
    session = requests.Session()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-card-generator",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    session.headers.update(headers)
    return session


def get_json(session: requests.Session, url: str, **params):
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_user(session: requests.Session, username: str) -> dict:
    return get_json(session, f"{API_ROOT}/users/{username}")


def fetch_repos(session: requests.Session, username: str) -> list[dict]:
    repos: list[dict] = []
    for page in range(1, 11):
        chunk = get_json(
            session,
            f"{API_ROOT}/users/{username}/repos",
            per_page=100,
            page=page,
            type="owner",
            sort="updated",
        )
        if not isinstance(chunk, list) or not chunk:
            break
        repos.extend(chunk)
        if len(chunk) < 100:
            break
    return repos


def repo_summary(repo: dict) -> dict:
    return {
        "name": repo.get("name") or "",
        "description": repo.get("description") or "",
        "url": repo.get("html_url") or "",
        "language": repo.get("language") or "",
        "stars": int(repo.get("stargazers_count") or 0),
        "forks": int(repo.get("forks_count") or 0),
        "updated_at": repo.get("pushed_at") or repo.get("updated_at") or "",
        "topics": repo.get("topics") or [],
        "homepage": repo.get("homepage") or "",
        "private": bool(repo.get("private")),
        "archived": bool(repo.get("archived")),
        "size": int(repo.get("size") or 0),
    }


def build_stats(username: str, user: dict, repos: list[dict]) -> dict:
    source = [
        repo
        for repo in repos
        if not repo.get("fork") and not repo.get("private")
    ]
    stars = sum(int(repo.get("stargazers_count") or 0) for repo in source)

    weights: dict[str, int] = {}
    for repo in source:
        language = repo.get("language")
        if not language:
            continue
        weights[language] = weights.get(language, 0) + max(
            int(repo.get("size") or 1), 1
        )

    total_weight = sum(weights.values())
    top_languages = [
        {
            "name": name,
            "percent": round(weight * 100 / total_weight, 1) if total_weight else 0.0,
        }
        for name, weight in sorted(
            weights.items(), key=lambda item: item[1], reverse=True
        )[:6]
    ]

    repositories = sorted(
        (repo_summary(repo) for repo in source),
        key=lambda item: (item["stars"], item["updated_at"]),
        reverse=True,
    )

    return {
        "username": username,
        "public_repos": int(user.get("public_repos") or len(source)),
        "total_stars": stars,
        "followers": int(user.get("followers") or 0),
        "following": int(user.get("following") or 0),
        "account_created": user.get("created_at"),
        "top_languages": top_languages,
        "repositories": repositories,
    }


def collect_stats(
    username: str, token: str | None, offline: bool, cache_path: Path
) -> dict:
    cached = load_json(cache_path, {}) or {}
    if offline:
        if not cached:
            raise SystemExit(
                f"No cached stats at {cache_path}; run once without --offline."
            )
        return cached

    session = github_session(token)
    try:
        user = fetch_user(session, username)
        repos = fetch_repos(session, username)
        stats = build_stats(username, user, repos)
    except requests.RequestException as exc:
        if cached:
            print(
                f"warning: GitHub fetch failed ({exc}); using cached stats",
                file=sys.stderr,
            )
            return cached
        raise SystemExit(f"GitHub fetch failed and no cache exists: {exc}")

    previous = {key: value for key, value in cached.items() if key != "generated_at"}
    if previous and previous == stats and cached.get("generated_at"):
        stats["generated_at"] = cached["generated_at"]
    else:
        stats["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return stats


def scrape_contributions(username: str):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html",
    }
    response = requests.get(
        PUBLIC_CONTRIB.format(username=username), headers=headers, timeout=30
    )
    response.raise_for_status()
    html = response.text

    dates: dict[str, tuple[str, int]] = {}
    for tag in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        day_id = re.search(r'id="([^"]+)"', tag)
        day_date = re.search(r'data-date="([^"]+)"', tag)
        day_level = re.search(r'data-level="([^"]+)"', tag)
        if day_id and day_date:
            dates[day_id.group(1)] = (
                day_date.group(1),
                int(day_level.group(1)) if day_level else 0,
            )

    counts: dict[str, int] = {}
    for key, text in re.findall(
        r'<tool-tip[^>]*for="([^"]+)"[^>]*>(.*?)</tool-tip>', html, re.S
    ):
        plain = re.sub(r"<[^>]+>", "", text).strip()
        if plain.startswith("No contributions"):
            counts[key] = 0
            continue
        match = re.match(r"(\d[\d,]*)\s+contribution", plain)
        if match:
            counts[key] = int(match.group(1).replace(",", ""))

    days = []
    for key, (day_date, level) in dates.items():
        if key not in counts:
            continue
        days.append({"date": day_date, "count": counts[key], "level": level})
    if not days:
        return None
    days.sort(key=lambda item: item["date"])
    return {"source": "github-public-html", "days": days}


def fetch_contributions_graphql(session: requests.Session, username: str):
    today = today_utc()
    start = today - timedelta(days=364)
    variables = {
        "login": username,
        "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{today.isoformat()}T23:59:59Z",
    }
    try:
        response = session.post(
            f"{API_ROOT}/graphql",
            json={"query": CONTRIBUTIONS_QUERY, "variables": variables},
            timeout=30,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        weeks = payload["data"]["user"]["contributionsCollection"][
            "contributionCalendar"
        ]["weeks"]
        raw = [
            day
            for week in weeks
            for day in week.get("contributionDays", [])
            if day.get("date")
        ]
        if not raw:
            return None
        top = max(int(day.get("contributionCount") or 0) for day in raw)
        days = [
            {
                "date": day["date"],
                "count": int(day.get("contributionCount") or 0),
                "level": level_for_count(
                    int(day.get("contributionCount") or 0), top
                ),
            }
            for day in raw
        ]
        days.sort(key=lambda item: item["date"])
        return {"source": "github-graphql", "days": days}
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None


def summarize_contributions(days: list[dict]) -> dict:
    today = today_utc()
    clean = [
        {
            "date": str(item["date"])[:10],
            "count": int(item.get("count") or 0),
            "level": int(item.get("level") or 0),
        }
        for item in days
        if str(item.get("date", ""))[:10] <= today.isoformat()
    ]
    clean.sort(key=lambda item: item["date"])
    counts = {item["date"]: item["count"] for item in clean}
    total = sum(item["count"] for item in clean)
    active_days = sum(1 for item in clean if item["count"] > 0)

    busiest = None
    if clean and total:
        best = max(clean, key=lambda item: (item["count"], item["date"]))
        busiest = {"date": best["date"], "count": best["count"]}

    longest = 0
    run = 0
    for item in clean:
        if item["count"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    cursor = today
    if counts.get(cursor.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    current = 0
    while counts.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    monthly_counts: dict[str, int] = {}
    for item in clean:
        monthly_counts[item["date"][:7]] = monthly_counts.get(item["date"][:7], 0) + item["count"]
    monthly = [
        {"month": key, "label": month_label(key), "count": monthly_counts.get(key, 0)}
        for key in month_keys(today, 12)
    ]

    return {
        "range": {
            "from": clean[0]["date"] if clean else "",
            "to": clean[-1]["date"] if clean else "",
        },
        "total": total,
        "active_days": active_days,
        "current_streak": current,
        "longest_streak": longest,
        "busiest": busiest,
        "monthly": monthly,
    }


def collect_contributions(
    username: str, token: str | None, offline: bool, cache_path: Path
) -> dict:
    cached = load_json(cache_path, {}) or {}
    if offline:
        if cached and "monthly" not in cached and cached.get("days"):
            cached.update(summarize_contributions(cached["days"]))
        return cached

    session = github_session(token)
    data = None
    if token:
        data = fetch_contributions_graphql(session, username)
    if data is None:
        try:
            data = scrape_contributions(username)
        except requests.RequestException as exc:
            print(f"warning: contribution fetch failed ({exc})", file=sys.stderr)

    if data is None:
        if cached:
            return cached
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "unavailable",
            "range": {"from": "", "to": ""},
            "total": 0,
            "active_days": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "busiest": None,
            "monthly": [
                {"month": key, "label": month_label(key), "count": 0}
                for key in month_keys(today_utc(), 12)
            ],
            "days": [],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": data["source"],
        **summarize_contributions(data["days"]),
        "days": data["days"],
    }


def is_eligible_repo(repo: dict, username: str) -> bool:
    name = str(repo.get("name") or "").strip()
    if not name or name.lower() == str(username).lower():
        return False
    if repo.get("private") or repo.get("fork"):
        return False
    return bool(repo.get("description") or repo.get("language") or repo.get("size"))


def resolve_repo_description(repo: dict, overrides: dict | None) -> str:
    description = str(repo.get("description") or "").strip()
    if description:
        return description

    overrides = overrides or {}
    name = str(repo.get("name") or "")
    for key in (name, name.lower()):
        value = overrides.get(key)
        if value and str(value).strip():
            return str(value).strip()

    language = str(repo.get("language") or "").strip()
    if language:
        return f"Public {language} project. No description provided."
    return "Public repository. No description provided."


def select_featured(
    repositories: list[dict],
    configured: list | None,
    username: str,
    limit: int = 4,
) -> list[dict]:
    eligible = [
        repo for repo in repositories if is_eligible_repo(repo, username)
    ]
    if configured:
        index = {str(repo.get("name", "")).lower(): repo for repo in eligible}
        selected = []
        for name in configured:
            repo = index.get(str(name).lower())
            if repo and repo not in selected:
                selected.append(repo)
        if selected:
            return selected[:limit]
    return eligible[:limit]


def render_hero(profile: dict, stats: dict, theme: dict) -> str:
    width, height = 1000, 450
    brand = str(profile.get("brand") or "BIDYA").upper()
    name = str(profile.get("name") or profile.get("username") or "").strip()
    role = str(profile.get("role") or "Visual Designer & Video Editor").strip()
    website = clean_url(str(profile.get("website") or "sorenverse.vercel.app"))
    services = profile.get("services") or profile.get("skills") or []
    headline = [
        str(line).upper()
        for line in (profile.get("headline") or ["I CREATE VISUALS", "THAT MAKE IDEAS"])
    ][:2]
    headline_accent = str(profile.get("headline_accent") or "feel alive.")
    intro = str(profile.get("bio") or profile.get("tagline") or "").strip()
    intro_lines = wrap_text(intro, 640, 11.5, factor=0.52, max_lines=3)
    name_suffix = name.upper()
    if name_suffix.startswith(brand):
        name_suffix = name_suffix[len(brand):].strip()

    portrait_path = profile.get("portrait")
    portrait_uri = image_uri(str(ROOT / portrait_path)) if portrait_path else None

    parts = [
        svg_header(width, height, f"{brand} \u2014 {name}"),
        frame(width, height, theme),
        accent_mark(32, 29, theme, css_class=anim("fade", "d1")),
        text_tag(
            48,
            42,
            brand,
            size=18,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-0.6,
            css_class=anim("rise", "d1"),
        ),
        text_tag(
            136,
            38,
            f"{name_suffix} \u2014 {role.upper()}",
            size=8.5,
            fill=theme["text"],
            family=MONO,
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        text_tag(
            968,
            36,
            f"PORTFOLIO \u2014 {today_utc().year}",
            size=9,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.4,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="32" y1="54" x2="968" y2="54" stroke="{theme["border"]}"/>',
    ]

    headline_lines = headline + [""] * (2 - len(headline))
    for index, line in enumerate(headline_lines):
        if line:
            parts.append(
                text_tag(
                    32,
                    118 + index * 52,
                    line,
                    size=42,
                    fill=theme["title"],
                    family=DISPLAY,
                    weight=800,
                    spacing=-1.8,
                    css_class=anim("rise", f"d{index + 2}"),
                )
            )

    parts.append(
        text_tag(
            29,
            232,
            headline_accent,
            size=56,
            fill=theme["accent"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("rise", "d4"),
        )
    )

    for index, line in enumerate(intro_lines):
        parts.append(
            text_tag(
                32,
                272 + index * 19,
                line,
                size=11.5,
                fill=theme["text"],
                family=BODY,
                weight=400,
                css_class=anim("fade", "d5"),
            )
        )

    portrait_defs = (
        f'<defs><clipPath id="heroPortrait">'
        f'<rect x="716" y="86" width="248" height="268"/></clipPath></defs>'
    )
    parts.append(portrait_defs)
    if portrait_uri:
        parts.extend(
            [
                image_tag(716, 86, 248, 268, portrait_uri, "heroPortrait", anim("fade", "d3")),
                rect(716.5, 86.5, 247, 267, "none", theme["border"]),
                accent_mark(708, 78, theme, 8, anim("fade", "d4")),
                text_tag(
                    716,
                    372,
                    "STUDIO PORTRAIT \u2014 BIDYA SAGAR SOREN",
                    size=8,
                    fill=theme["muted"],
                    family=MONO,
                    spacing=1.8,
                    css_class=anim("fade", "d5"),
                ),
            ]
        )
    else:
        parts.extend(
            [
                rect(716, 86, 248, 268, theme["surface"], theme["border"]),
                text_tag(
                    840,
                    240,
                    "B",
                    size=130,
                    fill=theme["accent"],
                    family=DISPLAY,
                    weight=800,
                    anchor="middle",
                    css_class=anim("fade", "d3"),
                ),
                text_tag(
                    716,
                    372,
                    "MONOGRAM \u2014 BIDYA SAGAR SOREN",
                    size=8,
                    fill=theme["muted"],
                    family=MONO,
                    spacing=1.8,
                    css_class=anim("fade", "d5"),
                ),
            ]
        )

    parts.extend(
        [
            f'<line x1="32" y1="402" x2="968" y2="402" stroke="{theme["border"]}"/>',
            accent_mark(32, 416, theme, 5, anim("fade", "d6")),
            text_tag(
                48,
                424,
                " / ".join(str(item).upper() for item in services[:4]),
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            text_tag(
                968,
                424,
                website.upper(),
                size=8.5,
                fill=theme["text"],
                family=MONO,
                anchor="end",
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            "</svg>",
        ]
    )
    return "".join(parts)


def render_about(profile: dict, theme: dict) -> str:
    width, height = 1000, 330
    pad = 32
    role = str(profile.get("role") or "").upper()
    location = str(profile.get("location") or "").upper()
    website = clean_url(str(profile.get("website") or "")).upper()
    about = str(profile.get("about") or profile.get("bio") or "").strip()
    about_lines = wrap_text(about, 600, 11.5, factor=0.52, max_lines=2)
    services = [
        str(item).upper()
        for item in (profile.get("services") or [])
        if str(item).strip()
    ][:4]

    parts = [
        svg_header(width, height, "About BIDYA"),
        frame(width, height, theme),
        section_label(pad, 34, "01", "About", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            "INDEPENDENT CREATIVE PRACTICE",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
        text_tag(
            pad,
            112,
            "INDEPENDENT",
            size=42,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-1.6,
            css_class=anim("rise", "d2"),
        ),
        text_tag(
            pad,
            160,
            "visual designer",
            size=44,
            fill=theme["accent"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("rise", "d3"),
        ),
        text_tag(
            pad,
            198,
            "& video editor.",
            size=30,
            fill=theme["title"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("fade", "d4"),
        ),
    ]

    for index, line in enumerate(about_lines):
        parts.append(
            text_tag(
                pad,
                238 + index * 19,
                line,
                size=11.5,
                fill=theme["text"],
                family=BODY,
                css_class=anim("fade", "d5"),
            )
        )

    parts.extend(
        [
            f'<line x1="{pad}" y1="284" x2="{width - pad}" y2="284" stroke="{theme["border"]}"/>',
            accent_mark(pad, 298, theme, 5, anim("fade", "d6")),
            text_tag(
                pad + 14,
                306,
                " / ".join(services),
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            f'<line x1="700" y1="70" x2="700" y2="284" stroke="{theme["border"]}"/>',
            accent_mark(724, 78, theme, 6, anim("fade", "d2")),
            text_tag(
                738,
                86,
                "PROFILE / 01",
                size=8,
                fill=theme["accent"],
                family=MONO,
                spacing=1.8,
                css_class=anim("fade", "d2"),
            ),
        ]
    )

    meta = [
        ("ROLE", role, 128, 146),
        ("BASED IN", location, 186, 204),
        ("PORTFOLIO", website, 244, 262),
    ]
    for label, value, label_y, value_y in meta:
        parts.append(
            text_tag(
                724,
                label_y,
                label,
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=1.6,
                css_class=anim("fade", "d4"),
            )
        )
        for index, line in enumerate(wrap_text(value, 236, 11, factor=0.58, max_lines=2)):
            parts.append(
                text_tag(
                    724,
                    value_y + index * 15,
                    line,
                    size=11,
                    fill=theme["title"],
                    family=MONO,
                    spacing=1.2,
                    css_class=anim("fade", "d4"),
                )
            )

    parts.append(
        text_tag(
            width - pad,
            306,
            "OPEN FOR SELECT PROJECTS",
            size=8,
            fill=theme["accent"],
            family=MONO,
            anchor="end",
            spacing=1.8,
            css_class=anim("fade", "d6"),
        )
    )
    parts.append("</svg>")
    return "".join(parts)


def render_work_intro(profile: dict, theme: dict) -> str:
    width, height = 1000, 170
    pad = 32

    return "".join(
        [
            svg_header(width, height, "Selected work"),
            frame(width, height, theme),
            section_label(pad, 34, "02", "Selected work", theme, anim("fade", "d1")),
            text_tag(
                width - pad,
                34,
                "SORENVERSE / ARCHIVE",
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=2.2,
                css_class=anim("fade", "d1"),
            ),
            f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                112,
                "SELECTED",
                size=42,
                fill=theme["title"],
                family=DISPLAY,
                weight=800,
                spacing=-1.6,
                css_class=anim("rise", "d2"),
            ),
            text_tag(
                414,
                116,
                "work.",
                size=46,
                fill=theme["accent"],
                family=SERIF,
                weight=400,
                italic=True,
                css_class=anim("rise", "d3"),
            ),
            text_tag(
                width - pad,
                96,
                "GRAPHIC DESIGN / VIDEO EDITING",
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=1.8,
                css_class=anim("fade", "d2"),
            ),
            text_tag(
                width - pad,
                112,
                "BRANDING / CAMPAIGNS / MOTION",
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=1.8,
                css_class=anim("fade", "d2"),
            ),
            f'<line x1="{pad}" y1="142" x2="{width - pad}" y2="142" stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                160,
                "THREE SELECTED PROJECTS \u2014 2025 / 2026",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=2,
                css_class=anim("fade", "d4"),
            ),
            text_tag(
                width - pad,
                160,
                "FULL ARCHIVE AT SORENVERSE",
                size=8,
                fill=theme["text"],
                family=MONO,
                anchor="end",
                spacing=2,
                css_class=anim("fade", "d4"),
            ),
            "</svg>",
        ]
    )


def render_toolkit(profile: dict, theme: dict) -> str:
    width, height = 1000, 310
    pad = 32
    inner = width - pad * 2
    groups = list(profile.get("toolkit") or [])
    if not groups:
        groups = [
            {
                "label": "Tools",
                "items": [str(item) for item in (profile.get("tools") or [])][:5],
            }
        ]
    groups = groups[:4]
    column = inner / 4

    parts = [
        svg_header(width, height, "Creative toolkit"),
        frame(width, height, theme),
        section_label(pad, 34, "03", "Creative toolkit", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            "TOOLS & TECHNOLOGIES",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
    ]

    for index, group in enumerate(groups):
        divider = pad + column * index
        content_x = pad if index == 0 else divider + 24
        if index:
            parts.append(
                f'<line x1="{divider:.1f}" y1="70" x2="{divider:.1f}" y2="266" '
                f'stroke="{theme["border"]}"/>'
            )
        parts.append(
            text_tag(
                content_x,
                84,
                str(group.get("label") or "").upper(),
                size=8.5,
                fill=theme["accent"],
                family=MONO,
                spacing=2.2,
                css_class=anim("fade", f"d{index + 2}"),
            )
        )
        for item_index, item in enumerate(group.get("items") or []):
            parts.append(
                text_tag(
                    content_x,
                    116 + item_index * 26,
                    str(item).upper(),
                    size=12,
                    fill=theme["title"],
                    family=DISPLAY,
                    weight=700,
                    spacing=-0.2,
                    css_class=anim("rise", f"d{min(item_index + 2, 8)}"),
                )
            )

    parts.extend(
        [
            f'<line x1="{pad}" y1="286" x2="{width - pad}" y2="286" stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                302,
                "SELECTED TOOLS \u2014 BRAND / FILM / DIGITAL",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            text_tag(
                width - pad,
                302,
                "ADOBE / DAVINCI / FIGMA / AI",
                size=8,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            "</svg>",
        ]
    )
    return "".join(parts)


def render_exploring(profile: dict, theme: dict) -> str:
    width, height = 1000, 270
    pad = 32
    inner = width - pad * 2
    items = [
        str(item).strip()
        for item in (profile.get("exploring") or [])
        if str(item).strip()
    ][:4]
    if not items:
        items = [
            "Creative technology",
            "AI-powered workflows",
            "Visual storytelling",
            "Digital experiences",
        ]
    column = inner / 4
    updated = today_utc().strftime("%b %Y").upper()

    parts = [
        svg_header(width, height, "Currently exploring"),
        frame(width, height, theme),
        section_label(pad, 34, "06", "Currently exploring", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            "ONGOING RESEARCH",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
        text_tag(
            pad,
            112,
            "WHERE THE WORK",
            size=42,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-1.6,
            css_class=anim("rise", "d2"),
        ),
        text_tag(
            716,
            116,
            "is heading.",
            size=46,
            fill=theme["accent"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("rise", "d3"),
        ),
        f'<line x1="{pad}" y1="152" x2="{width - pad}" y2="152" stroke="{theme["border"]}"/>',
    ]

    for index, item in enumerate(items):
        divider = pad + column * index
        content_x = pad if index == 0 else divider + 18
        if index:
            parts.append(
                f'<line x1="{divider:.1f}" y1="170" x2="{divider:.1f}" y2="228" '
                f'stroke="{theme["border"]}"/>'
            )
        parts.append(
            text_tag(
                content_x,
                186,
                f"{index + 1:02d}",
                size=8,
                fill=theme["accent"],
                family=MONO,
                spacing=1.8,
                css_class=anim("fade", f"d{index + 2}"),
            )
        )
        for line_index, line in enumerate(
            wrap_text(item.upper(), 200, 12, factor=0.9, max_lines=2)
        ):
            parts.append(
                text_tag(
                    content_x,
                    210 + line_index * 16,
                    line,
                    size=12,
                    fill=theme["title"],
                    family=DISPLAY,
                    weight=700,
                    spacing=-0.2,
                    css_class=anim("rise", f"d{min(index + 2, 8)}"),
                )
            )

    parts.extend(
        [
            f'<line x1="{pad}" y1="242" x2="{width - pad}" y2="242" stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                258,
                "A ROLLING STUDIO NOTE",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            text_tag(
                width - pad,
                258,
                f"UPDATED \u2014 {updated}",
                size=8,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=2,
                css_class=anim("fade", "d6"),
            ),
            "</svg>",
        ]
    )
    return "".join(parts)


def render_connect(profile: dict, theme: dict) -> str:
    width, height = 1000, 200
    pad = 32
    socials = profile.get("socials") or {}
    website = clean_url(str(profile.get("website") or "")).upper()
    instagram = clean_url(str(socials.get("instagram") or ""))
    handle = instagram.split("/")[-1] if instagram else ""
    email = str(socials.get("email") or "").upper()

    rows = [
        ("PORTFOLIO", website, 86, 102),
        ("INSTAGRAM", f"@{handle}".upper(), 128, 144),
        ("EMAIL", email, 168, 184),
    ]

    parts = [
        svg_header(width, height, "Connect"),
        frame(width, height, theme),
        section_label(pad, 34, "07", "Connect", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            "OPEN FOR SELECT PROJECTS",
            size=8.5,
            fill=theme["accent"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
        text_tag(
            pad,
            112,
            "LET'S MAKE",
            size=42,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-1.6,
            css_class=anim("rise", "d2"),
        ),
        text_tag(
                444,
                116,
                "something.",
            size=46,
            fill=theme["accent"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("rise", "d3"),
        ),
        text_tag(
            pad,
            158,
            "COLLABORATIONS / COMMISSIONS / CREATIVE DIRECTION",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            spacing=2,
            css_class=anim("fade", "d4"),
        ),
        f'<line x1="700" y1="70" x2="700" y2="188" stroke="{theme["border"]}"/>',
    ]

    for label, value, label_y, value_y in rows:
        parts.append(
            text_tag(
                724,
                label_y,
                label,
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=1.6,
                css_class=anim("fade", "d2"),
            )
        )
        parts.append(
            text_tag(
                724,
                value_y,
                value,
                size=10.5,
                fill=theme["title"],
                family=MONO,
                spacing=1.2,
                css_class=anim("fade", "d2"),
            )
        )

    parts.append("</svg>")
    return "".join(parts)


def render_stats(stats: dict, theme: dict) -> str:
    width, height = 1000, 210
    pad = 32
    inner = width - pad * 2

    items = [
        ("01", format_number(stats.get("public_repos")), "REPOSITORIES"),
        ("02", format_number(stats.get("total_stars")), "STARS EARNED"),
        ("03", format_number(stats.get("followers")), "FOLLOWERS"),
        ("04", format_number(stats.get("following")), "FOLLOWING"),
    ]
    column = inner / len(items)

    parts = [
        svg_header(width, height, "GitHub index"),
        frame(width, height, theme),
        section_label(pad, 34, "04", "GitHub activity", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            "BIDYA / SORENVERSE",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
    ]

    for index, (number, value, label) in enumerate(items):
        divider = pad + column * index
        content_x = pad if index == 0 else divider + 20
        if index:
            parts.append(
                f'<line x1="{divider:.1f}" y1="64" x2="{divider:.1f}" y2="158" '
                f'stroke="{theme["border"]}"/>'
            )
        parts.extend(
            [
                text_tag(
                    content_x,
                    80,
                    number,
                    size=8,
                    fill=theme["accent"],
                    family=MONO,
                    spacing=1.8,
                    css_class=anim("fade", f"d{index + 2}"),
                ),
                text_tag(
                    content_x,
                    126,
                    value,
                    size=50,
                    fill=theme["title"],
                    family=MONO,
                    weight=400,
                    spacing=0,
                    css_class=anim("rise", f"d{index + 2}"),
                ),
                text_tag(
                    content_x,
                    150,
                    label,
                    size=8.5,
                    fill=theme["muted"],
                    family=MONO,
                    spacing=2,
                    css_class=anim("fade", f"d{index + 4}"),
                ),
            ]
        )

    parts.append(
        f'<line x1="{pad}" y1="172" x2="{width - pad}" y2="172" stroke="{theme["border"]}"/>'
    )
    parts.append(
        text_tag(
            pad,
            196,
            f"@{stats.get('username', '')}",
            size=8.5,
            fill=theme["text"],
            family=MONO,
            spacing=1.8,
            css_class=anim("fade", "d6"),
        )
    )
    since = month_year(stats.get("account_created"))
    if since:
        parts.append(
            text_tag(
                width / 2,
                196,
                f"MEMBER SINCE {since}",
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                anchor="middle",
                spacing=2,
                css_class=anim("fade", "d6"),
            )
        )
    updated = short_date(stats.get("generated_at"))
    if updated:
        parts.append(
            text_tag(
                width - pad,
                196,
                f"UPDATED {updated}",
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=2,
                css_class=anim("fade", "d6"),
            )
        )

    parts.append("</svg>")
    return "".join(parts)


def render_activity(contrib: dict, theme: dict) -> str:
    width, height = 1000, 360
    pad = 32
    inner = width - pad * 2

    current = int(contrib.get("current_streak") or 0)
    longest = int(contrib.get("longest_streak") or 0)
    active = int(contrib.get("active_days") or 0)
    busiest = contrib.get("busiest") or {}
    total = int(contrib.get("total") or 0)

    def streak_label(value: int) -> str:
        return f"{value} DAY" if value == 1 else f"{value} DAYS"

    busiest_value = short_day(busiest.get("date")) if busiest else "\u2014"
    busiest_detail = (
        f"{busiest.get('count', 0)} CONTRIBUTION"
        + ("S" if int(busiest.get("count") or 0) != 1 else "")
        if busiest
        else "NO ACTIVITY YET"
    )

    metrics = [
        ("01", streak_label(current), "CURRENT STREAK", ""),
        ("02", streak_label(longest), "LONGEST STREAK", ""),
        ("03", format_number(active), "ACTIVE DAYS", ""),
        ("04", busiest_value, "BUSIEST DAY", busiest_detail),
    ]

    parts = [
        svg_header(width, height, "GitHub activity"),
        frame(width, height, theme),
        section_label(pad, 34, "04", "Contribution streak", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            "PUBLIC CONTRIBUTION CALENDAR",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
    ]

    column = inner / 4
    for index, (number, value, label, detail) in enumerate(metrics):
        divider = pad + column * index
        content_x = pad if index == 0 else divider + 20
        if index:
            parts.append(
                f'<line x1="{divider:.1f}" y1="64" x2="{divider:.1f}" y2="160" '
                f'stroke="{theme["border"]}"/>'
            )
        parts.extend(
            [
                text_tag(
                    content_x,
                    80,
                    number,
                    size=8,
                    fill=theme["accent"],
                    family=MONO,
                    spacing=1.8,
                    css_class=anim("fade", f"d{index + 2}"),
                ),
                text_tag(
                    content_x,
                    118,
                    value,
                    size=28,
                    fill=theme["title"],
                    family=MONO,
                    weight=400,
                    css_class=anim("rise", f"d{index + 2}"),
                ),
                text_tag(
                    content_x,
                    140,
                    label,
                    size=8.5,
                    fill=theme["muted"],
                    family=MONO,
                    spacing=2,
                    css_class=anim("fade", f"d{index + 3}"),
                ),
            ]
        )
        if detail:
            parts.append(
                text_tag(
                    content_x,
                    156,
                    detail,
                    size=7.5,
                    fill=theme["text"],
                    family=MONO,
                    spacing=1.4,
                    css_class=anim("fade", f"d{index + 3}"),
                )
            )

    parts.extend(
        [
            f'<line x1="{pad}" y1="174" x2="{width - pad}" y2="174" stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                198,
                "MONTHLY CONTRIBUTIONS \u2014 LAST 12 MONTHS",
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                spacing=2,
                css_class=anim("fade", "d3"),
            ),
            text_tag(
                width - pad,
                198,
                f"TOTAL {format_number(total)}",
                size=8.5,
                fill=theme["accent"],
                family=MONO,
                anchor="end",
                spacing=2,
                css_class=anim("fade", "d3"),
            ),
        ]
    )

    monthly = list(contrib.get("monthly") or [])
    if len(monthly) < 12:
        by_month = {item["month"]: item["count"] for item in monthly}
        monthly = [
            {"month": key, "label": month_label(key), "count": by_month.get(key, 0)}
            for key in month_keys(today_utc(), 12)
        ]
    max_count = max((int(item.get("count") or 0) for item in monthly), default=0) or 1
    baseline, plot_height = 300, 80
    bar_width = 44
    gap = (inner - bar_width * 12) / 11

    for index, item in enumerate(monthly):
        count = int(item.get("count") or 0)
        height_value = max(2, count / max_count * plot_height)
        x = pad + index * (bar_width + gap)
        y = baseline - height_value
        fill = theme["accent"] if count > 0 else "#FFFFFF14"
        parts.append(
            rect(
                round(x, 2),
                round(y, 2),
                bar_width,
                round(height_value, 2),
                fill,
                css_class=anim("growY", f"d{(index % 10) + 1}"),
            )
        )
        if count > 0:
            parts.append(
                text_tag(
                    round(x + bar_width / 2, 2),
                    round(y - 8, 2),
                    format_number(count),
                    size=9,
                    fill=theme["text"],
                    family=MONO,
                    anchor="middle",
                    spacing=1,
                    css_class=anim("fade", f"d{(index % 10) + 1}"),
                )
            )
        parts.append(
            text_tag(
                round(x + bar_width / 2, 2),
                322,
                str(item.get("label") or month_label(str(item.get("month", "")))),
                size=8,
                fill=theme["muted"],
                family=MONO,
                anchor="middle",
                spacing=1.4,
                css_class=anim("fade", f"d{(index % 10) + 1}"),
            )
        )

    source = {
        "github-graphql": "GITHUB GRAPHQL",
        "github-public-html": "GITHUB PUBLIC CALENDAR",
        "unavailable": "GITHUB CALENDAR UNAVAILABLE",
    }.get(str(contrib.get("source")), "GITHUB CALENDAR")
    range_value = contrib.get("range") or {}
    range_label = ""
    if range_value.get("from") and range_value.get("to"):
        range_label = f"{short_date(range_value['from'])} \u2014 {short_date(range_value['to'])}"

    parts.extend(
        [
            f'<line x1="{pad}" y1="338" x2="{width - pad}" y2="338" stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                356,
                f"SOURCE \u2014 {source}",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=1.8,
                css_class=anim("fade", "d6"),
            ),
            text_tag(
                width - pad,
                356,
                range_label,
                size=8,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=1.8,
                css_class=anim("fade", "d6"),
            ),
            "</svg>",
        ]
    )
    return "".join(parts)


def render_heatmap(contrib: dict, theme: dict) -> str:
    width, height = 1000, 250
    pad = 32
    daily = {item["date"]: item for item in (contrib.get("days") or [])}
    today = today_utc()

    week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    start = week_start - timedelta(weeks=52)
    grid_x, grid_y = 64, 84
    step, cell = 16, 12
    weeks = 53

    def cell_fill(level: int):
        if level < 0:
            return None
        if level == 0:
            return "#FFFFFF0D"
        opacity = {1: 0.25, 2: 0.5, 3: 0.75, 4: 1.0}.get(level, 1.0)
        return theme["accent"], opacity

    parts = [
        svg_header(width, height, "Contribution heatmap"),
        frame(width, height, theme),
        section_label(pad, 34, "04", "Contribution map", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            f"{format_number(contrib.get('total'))} CONTRIBUTIONS",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=2.2,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
    ]

    month_x = -100
    for week in range(weeks):
        for weekday in range(7):
            current = start + timedelta(weeks=week, days=weekday)
            if current.day == 1 and week > 0:
                if grid_x + week * step - month_x >= 40:
                    parts.append(
                        text_tag(
                            grid_x + week * step,
                            74,
                            current.strftime("%b").upper(),
                            size=8,
                            fill=theme["muted"],
                            family=MONO,
                            spacing=1,
                            css_class=anim("fade", "d3"),
                        )
                    )
                    month_x = grid_x + week * step

    for row, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]):
        if name in {"MON", "WED", "FRI"}:
            parts.append(
                text_tag(
                    grid_x - 12,
                    grid_y + row * step + 9,
                    name,
                    size=7.5,
                    fill=theme["muted"],
                    family=MONO,
                    anchor="end",
                    spacing=1,
                )
            )

    for week in range(weeks):
        group = [f'<g{class_attr(anim("fade", f"d{(week % 10) + 1}"))}>']
        for row in range(7):
            current = start + timedelta(weeks=week, days=row)
            if current > today:
                level = -1
            else:
                entry = daily.get(current.isoformat())
                level = int(entry.get("level") or 0) if entry else 0
            color = cell_fill(level)
            if color is None:
                continue
            x = grid_x + week * step
            y = grid_y + row * step
            if isinstance(color, tuple):
                group.append(
                    rect(x, y, cell, cell, color[0], radius=2, opacity=color[1])
                )
            else:
                group.append(rect(x, y, cell, cell, color, radius=2))
        group.append("</g>")
        parts.append("".join(group))

    parts.append(
        f'<line x1="{pad}" y1="206" x2="{width - pad}" y2="206" stroke="{theme["border"]}"/>'
    )
    total = int(contrib.get("total") or 0)
    active = int(contrib.get("active_days") or 0)
    parts.append(
        text_tag(
            pad,
            230,
            f"{format_number(total)} CONTRIBUTIONS \u2014 {format_number(active)} ACTIVE DAYS"
            if total
            else "NO PUBLIC CONTRIBUTIONS YET",
            size=8.5,
            fill=theme["muted"],
            family=MONO,
            spacing=1.8,
            css_class=anim("fade", "d6"),
        )
    )

    range_value = contrib.get("range") or {}
    if range_value.get("from") and range_value.get("to"):
        parts.append(
            text_tag(
                width - pad,
                230,
                f"{short_date(range_value['from'])} \u2014 {short_date(range_value['to'])}",
                size=8,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=1.6,
                css_class=anim("fade", "d6"),
            )
        )

    legend_x, legend_y = 400, 222
    parts.append(
        text_tag(
            legend_x,
            230,
            "LESS",
            size=7.5,
            fill=theme["muted"],
            family=MONO,
            spacing=1.2,
            css_class=anim("fade", "d6"),
        )
    )
    for index, level in enumerate([0, 1, 2, 3, 4]):
        color = cell_fill(level)
        x = legend_x + 34 + index * 15
        if isinstance(color, tuple):
            parts.append(rect(x, legend_y, 11, 11, color[0], radius=2, opacity=color[1]))
        else:
            parts.append(rect(x, legend_y, 11, 11, color, radius=2))
    parts.append(
        text_tag(
            legend_x + 116,
            230,
            "MORE",
            size=7.5,
            fill=theme["muted"],
            family=MONO,
            spacing=1.2,
            css_class=anim("fade", "d6"),
        )
    )
    parts.append("</svg>")
    return "".join(parts)


def render_languages(stats: dict, theme: dict, min_height: int = 0) -> str:
    width = 495
    pad = 24
    inner = width - pad * 2
    languages = list(stats.get("top_languages") or [])[:5]
    start_y, row_step = 132, 40

    if languages:
        height = max(250, start_y + len(languages) * row_step + 46)
    else:
        height = 250
    height = max(height, min_height)

    parts = [
        svg_header(width, height, "Language index"),
        frame(width, height, theme),
        section_label(pad, 34, "04", "Language index", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            f"{len(languages):02d} TRACKED",
            size=8,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=1.8,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
        text_tag(
            pad,
            92,
            "Most used",
            size=24,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-0.8,
            css_class=anim("rise", "d2"),
        ),
        text_tag(
            228,
            94,
            "languages",
            size=28,
            fill=theme["accent"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("fade", "d2"),
        ),
    ]

    if not languages:
        parts.append(
            text_tag(
                pad,
                168,
                "AWAITING PUBLIC CODE",
                size=9,
                fill=theme["muted"],
                family=MONO,
                spacing=2.2,
            )
        )
    for index, language in enumerate(languages):
        name = str(language.get("name") or "Other").upper()
        percent = float(language.get("percent") or 0)
        baseline = start_y + index * row_step
        bar_width = inner * min(max(percent, 0.0), 100.0) / 100
        parts.extend(
            [
                text_tag(
                    pad,
                    baseline,
                    f"{index + 1:02d}",
                    size=8,
                    fill=theme["accent"],
                    family=MONO,
                    spacing=1.4,
                    css_class=anim("fade", f"d{index + 2}"),
                ),
                text_tag(
                    pad + 28,
                    baseline,
                    name,
                    size=15,
                    fill=theme["title"],
                    family=DISPLAY,
                    weight=700,
                    spacing=-0.2,
                    css_class=anim("rise", f"d{index + 2}"),
                ),
                text_tag(
                    width - pad,
                    baseline,
                    f"{percent:g}%",
                    size=9,
                    fill=theme["text"],
                    family=MONO,
                    anchor="end",
                    spacing=1.4,
                    css_class=anim("fade", f"d{index + 2}"),
                ),
                rect(pad, baseline + 12, inner, 2, "#FFFFFF12"),
                rect(
                    pad,
                    baseline + 12,
                    round(bar_width, 2),
                    2,
                    theme["accent"],
                    css_class=anim("grow", f"d{index + 2}"),
                ),
            ]
        )

    footer_y = height - 30
    parts.extend(
        [
            f'<line x1="{pad}" y1="{footer_y - 12}" x2="{width - pad}" y2="{footer_y - 12}" '
            f'stroke="{theme["border"]}"/>',
            text_tag(
                pad,
                footer_y,
                "MEASURED BY REPOSITORY SIZE \u2014 PUBLIC CODE ONLY",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=1.8,
                css_class=anim("fade", "d6"),
            ),
            "</svg>",
        ]
    )
    return "".join(parts)


def render_practice(profile: dict, theme: dict, min_height: int = 0) -> str:
    width = 495
    pad = 24
    inner = width - pad * 2
    services = [
        str(item).strip()
        for item in (profile.get("services") or [])
        if str(item).strip()
    ]
    if not services:
        services = [
            str(item).strip()
            for item in (profile.get("skills") or [])
            if str(item).strip()
        ]
    services = services[:6]
    tools = [
        str(item).strip().upper()
        for item in (profile.get("tools") or [])
        if str(item).strip()
    ]
    tool_text = "TOOLS \u2014 " + " / ".join(tools) if tools else ""
    tool_lines = wrap_text(tool_text, inner, 8.5, factor=0.6, spacing=1.5) if tool_text else []

    rows_top = 122
    rows_height = len(services) * 30
    tool_block = max(len(tool_lines), 1) * 14
    computed_top = rows_top + rows_height + 14
    computed_height = computed_top + 14 + tool_block + 22
    height = max(computed_height, min_height)
    tools_top = max(computed_top, height - 36 - tool_block)

    parts = [
        svg_header(width, height, "Creative practice"),
        frame(width, height, theme),
        section_label(pad, 34, "03", "Practice", theme, anim("fade", "d1")),
        text_tag(
            width - pad,
            34,
            f"{len(services):02d} DISCIPLINES",
            size=8,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=1.8,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
        text_tag(
            pad,
            92,
            "What I do",
            size=24,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-0.8,
            css_class=anim("rise", "d2"),
        ),
        text_tag(
            214,
            94,
            "with intent.",
            size=28,
            fill=theme["accent"],
            family=SERIF,
            weight=400,
            italic=True,
            css_class=anim("fade", "d2"),
        ),
    ]

    for index, service in enumerate(services):
        top = rows_top + index * 30
        parts.append(
            f'<line x1="{pad}" y1="{top}" x2="{width - pad}" y2="{top}" '
            f'stroke="{theme["border"]}"/>'
        )
        parts.extend(
            [
                text_tag(
                    pad,
                    top + 20,
                    f"{index + 1:02d}",
                    size=8,
                    fill=theme["accent"],
                    family=MONO,
                    spacing=1.4,
                    css_class=anim("fade", f"d{index + 2}"),
                ),
                text_tag(
                    pad + 30,
                    top + 20,
                    service.upper(),
                    size=14.5,
                    fill=theme["title"],
                    family=DISPLAY,
                    weight=700,
                    spacing=-0.2,
                    css_class=anim("rise", f"d{index + 2}"),
                ),
            ]
        )

    if not services:
        parts.append(
            text_tag(
                pad,
                rows_top + 20,
                "PRACTICE INDEX COMING SOON",
                size=9,
                fill=theme["muted"],
                family=MONO,
                spacing=2.2,
            )
        )

    parts.append(
        f'<line x1="{pad}" y1="{tools_top}" x2="{width - pad}" y2="{tools_top}" '
        f'stroke="{theme["border"]}"/>'
    )
    for index, line in enumerate(tool_lines or ["TOOLS \u2014 ADD YOUR KIT"]):
        parts.append(
            text_tag(
                pad,
                tools_top + 18 + index * 14,
                line,
                size=8.5,
                fill=theme["muted"],
                family=MONO,
                spacing=1.5,
                css_class=anim("fade", "d6"),
            )
        )

    parts.append("</svg>")
    return "".join(parts)


def render_tile(project: dict, index: int, theme: dict) -> str:
    width, height = 320, 430
    image_path = project.get("image")
    uri = image_uri(str(ROOT / image_path)) if image_path else None
    if not uri:
        raise SystemExit(
            f"Missing portfolio image for {project.get('title')!r}: {image_path}"
        )

    title = str(project.get("title") or "").strip()
    subtitle = str(project.get("subtitle") or "").strip()
    category = str(project.get("category") or "").strip()
    year = str(project.get("year") or "").strip()

    defs = (
        '<defs>'
        '<clipPath id="tileImage"><rect width="320" height="326"/></clipPath>'
        f'<linearGradient id="tileFade" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{theme["background"]}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{theme["background"]}" stop-opacity="0.92"/>'
        "</linearGradient>"
        "</defs>"
    )

    return "".join(
        [
            svg_header(width, height, f"{title} \u2014 {subtitle}"),
            frame(width, height, theme),
            defs,
            image_tag(0, 0, 320, 326, uri, "tileImage", anim("fade", "d1")),
            rect(0, 286, 320, 40, "url(#tileFade)"),
            f'<line x1="0" y1="326" x2="320" y2="326" stroke="{theme["border"]}"/>',
            accent_mark(20, 342, theme, 6, anim("fade", "d2")),
            text_tag(
                34,
                350,
                f"{index + 1:02d} / 03",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=1.8,
                css_class=anim("fade", "d2"),
            ),
            text_tag(
                20,
                384,
                title,
                size=20,
                fill=theme["title"],
                family=DISPLAY,
                weight=800,
                spacing=-0.6,
                css_class=anim("rise", "d3"),
            ),
            text_tag(
                20,
                404,
                subtitle.upper(),
                size=8.5,
                fill=theme["text"],
                family=MONO,
                spacing=1.8,
                css_class=anim("fade", "d4"),
            ),
            text_tag(
                20,
                420,
                f"{category} \u2014 {year}",
                size=7.5,
                fill=theme["muted"],
                family=MONO,
                spacing=1.6,
                css_class=anim("fade", "d4"),
            ),
            "</svg>",
        ]
    )


def render_repo(
    repo: dict, index: int, theme: dict, overrides: dict | None = None
) -> str:
    width, height = 495, 260
    pad = 24
    inner = width - pad * 2
    name = str(repo.get("name") or "UNKNOWN").upper()
    description = resolve_repo_description(repo, overrides)
    description_lines = wrap_text(description, inner, 11, factor=0.52, max_lines=3)
    language = str(repo.get("language") or "").upper()
    stars = int(repo.get("stars") or 0)
    forks = int(repo.get("forks") or 0)
    updated = short_date(repo.get("updated_at")) or "\u2014"

    parts = [
        svg_header(width, height, f"Featured repository \u2014 {name}"),
        frame(width, height, theme),
        section_label(
            pad, 34, "05", "Featured repository", theme, anim("fade", "d1")
        ),
        text_tag(
            width - pad,
            34,
            f"GITHUB / {index + 1:02d}",
            size=8,
            fill=theme["muted"],
            family=MONO,
            anchor="end",
            spacing=1.8,
            css_class=anim("fade", "d1"),
        ),
        f'<line x1="{pad}" y1="50" x2="{width - pad}" y2="50" stroke="{theme["border"]}"/>',
        mixed_text(
            pad,
            92,
            name,
            size=22,
            fill=theme["title"],
            family=DISPLAY,
            weight=800,
            spacing=-0.6,
            css_class=anim("rise", "d2"),
        ),
    ]

    for line_index, line in enumerate(description_lines):
        parts.append(
            text_tag(
                pad,
                120 + line_index * 18,
                line,
                size=11,
                fill=theme["text"],
                family=BODY,
                weight=400,
                css_class=anim("fade", "d3"),
            )
        )

    parts.extend(
        [
            f'<line x1="{pad}" y1="188" x2="{width - pad}" y2="188" stroke="{theme["border"]}"/>',
            accent_mark(pad, 208, theme, 5, anim("fade", "d4")),
            text_tag(
                pad + 12,
                214,
                language or "NO PRIMARY LANGUAGE",
                size=8,
                fill=theme["text"],
                family=MONO,
                spacing=1.6,
                css_class=anim("fade", "d4"),
            ),
            text_tag(
                pad,
                240,
                f"STARS {format_number(stars)} / FORKS {format_number(forks)}",
                size=8,
                fill=theme["muted"],
                family=MONO,
                spacing=1.6,
                css_class=anim("fade", "d5"),
            ),
            text_tag(
                width - pad,
                240,
                f"UPDATED {updated}",
                size=8,
                fill=theme["muted"],
                family=MONO,
                anchor="end",
                spacing=1.6,
                css_class=anim("fade", "d5"),
            ),
            "</svg>",
        ]
    )
    return "".join(parts)


def main(argv=None) -> int:
    global ANIMATE

    parser = argparse.ArgumentParser(
        description="Generate editorial SVG cards for a GitHub profile README."
    )
    parser.add_argument(
        "--offline", action="store_true", help="render from cached GitHub data"
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="render final-frame SVGs without animation CSS",
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--out", type=Path, default=CARDS_DIR)
    args = parser.parse_args(argv)

    env_static = os.environ.get("STATIC", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    ANIMATE = not (args.static or env_static)

    profile = load_json(args.config)
    if not profile:
        raise SystemExit(f"Missing profile configuration: {args.config}")

    username = str(profile.get("username") or "").strip()
    if not username:
        raise SystemExit("profile.json must define a username")

    portfolio = list(profile.get("portfolio") or [])
    if len(portfolio) != 3:
        raise SystemExit(
            "profile.json must define exactly three portfolio entries"
        )

    cache_path = args.config.with_name("github_stats.json")
    contrib_path = args.config.with_name("contributions.json")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    stats = collect_stats(username, token, args.offline, cache_path)
    contributions = collect_contributions(username, token, args.offline, contrib_path)

    if not args.offline:
        write_json(cache_path, stats)
        write_json(contrib_path, contributions)

    theme = dict(DEFAULT_THEME)
    theme.update(profile.get("theme") or {})

    repositories = list(stats.get("repositories") or [])
    featured = select_featured(
        repositories, profile.get("featured_repos"), username
    )
    description_overrides = profile.get("repo_descriptions") or {}

    args.out.mkdir(parents=True, exist_ok=True)
    for pattern in ("work-*.svg", "repo-*.svg"):
        for path in args.out.glob(pattern):
            path.unlink()
    stale = args.out / "skills.svg"
    if stale.exists():
        stale.unlink()

    (args.out / "hero.svg").write_text(
        render_hero(profile, stats, theme), encoding="utf-8"
    )
    (args.out / "stats.svg").write_text(
        render_stats(stats, theme), encoding="utf-8"
    )
    (args.out / "activity.svg").write_text(
        render_activity(contributions, theme), encoding="utf-8"
    )
    (args.out / "heatmap.svg").write_text(
        render_heatmap(contributions, theme), encoding="utf-8"
    )
    (args.out / "about.svg").write_text(
        render_about(profile, theme), encoding="utf-8"
    )
    (args.out / "selected-work.svg").write_text(
        render_work_intro(profile, theme), encoding="utf-8"
    )
    (args.out / "toolkit.svg").write_text(
        render_toolkit(profile, theme), encoding="utf-8"
    )
    (args.out / "exploring.svg").write_text(
        render_exploring(profile, theme), encoding="utf-8"
    )
    (args.out / "connect.svg").write_text(
        render_connect(profile, theme), encoding="utf-8"
    )
    (args.out / "languages.svg").write_text(
        render_languages(stats, theme), encoding="utf-8"
    )
    (args.out / "practice.svg").write_text(
        render_practice(profile, theme), encoding="utf-8"
    )

    for index, project in enumerate(portfolio):
        slug = safe_slug(project.get("slug") or project.get("title") or index)
        (args.out / f"work-{slug}.svg").write_text(
            render_tile(project, index, theme), encoding="utf-8"
        )

    for index, repo in enumerate(featured):
        slug = safe_slug(repo.get("name") or index)
        (args.out / f"repo-{slug}.svg").write_text(
            render_repo(repo, index, theme, description_overrides),
            encoding="utf-8",
        )

    mode = "static" if not ANIMATE else "animated"
    print(
        f"Generated {len(list(args.out.glob('*.svg')))} {mode} cards in {args.out}"
    )
    print(
        f"Contributions: {contributions.get('total', 0)} total | "
        f"{contributions.get('active_days', 0)} active days | "
        f"source={contributions.get('source', 'unknown')}"
    )
    print(f"Featured repositories: {', '.join(repo['name'] for repo in featured) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

