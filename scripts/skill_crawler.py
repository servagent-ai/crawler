#!/usr/bin/env python3
"""
ServAgent Skill Crawler
=======================
Crawls GitHub for high-quality MCP servers, Claude skills, and agent tools.
Scores each tool and filters out low-quality ones.
Target: 3000 high-quality skills in the cloud store.

Usage:
    export GITHUB_TOKEN=ghp_xxx
    python skill_crawler.py --max-repos 5000 --min-stars 10 --output skills-raw.json
    python skill_crawler.py --score --input skills-raw.json --output skills-scored.json
    python skill_crawler.py --upload --input skills-scored.json --api-url https://api.servagent.ai
"""

import os
import re
import json
import time
import hashlib
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Search queries — cast a wide net for MCP, skills, agent tools
SEARCH_QUERIES = [
    # MCP servers (official protocol)
    "topic:mcp-server",
    "topic:modelcontextprotocol",
    "mcp server in:name,description,readme stars:>10",
    "model context protocol server stars:>5",
    # Claude skills
    "topic:claude-skill",
    "claude skill in:name,description stars:>10",
    # Agent tools
    "topic:ai-agent-tool",
    "langchain tool in:name,description stars:>50",
    "openai function tool in:name,description stars:>50",
    # Popular tool categories
    "mcp web-search stars:>10",
    "mcp database stars:>10",
    "mcp file-system stars:>10",
    "mcp browser automation stars:>10",
    "mcp github integration stars:>10",
    "mcp slack integration stars:>10",
    "mcp notion integration stars:>10",
    "mcp gmail integration stars:>10",
    "mcp calendar integration stars:>10",
    "mcp code-execution stars:>5",
    # Large MCP collections
    "awesome-mcp in:name stars:>50",
    "mcp-servers in:name stars:>20",
    # OpenAI plugins / tools (compatible)
    "openai plugin in:name stars:>100",
    "chatgpt plugin stars:>50",
    # OpenClaw / ClawHub skills
    "topic:clawhub-server",
    "topic:openclaw-skill",
    "openclaw skill in:name,description stars:>5",
    "clawhub server in:name,description stars:>5",
    # Antigravity skills (22K star collection)
    "topic:antigravity-skill",
    "antigravity skill in:name,description stars:>5",
    "awesome-claude-skills in:name stars:>20",
    "claude-code skill in:name,description stars:>10",
    # More agent tools
    "topic:ai-tools",
    "agent tools mcp in:description stars:>20",
    "function calling tool openai in:description stars:>30",
    # Additional integrations
    "mcp stripe integration stars:>5",
    "mcp linear integration stars:>5",
    "mcp jira integration stars:>5",
    "mcp figma integration stars:>5",
    "mcp aws integration stars:>10",
    "mcp kubernetes integration stars:>5",
    "mcp docker integration stars:>5",
    "mcp redis integration stars:>5",
    "mcp mongodb integration stars:>5",
    "mcp elasticsearch integration stars:>5",
    # LLM frameworks with tool support
    "langchain agent tools stars:>100",
    "autogen tools stars:>50",
    "crewai tool in:name,description stars:>20",
    # Additional MCP integrations (less common)
    "mcp salesforce stars:>5",
    "mcp confluence stars:>5",
    "mcp hubspot stars:>5",
    "mcp zendesk stars:>5",
    "mcp shopify stars:>5",
    "mcp airtable stars:>5",
    "mcp trello stars:>5",
    "mcp asana stars:>5",
    "mcp clickup stars:>5",
    "mcp discord integration stars:>5",
    "mcp telegram bot stars:>5",
    "mcp twitter api stars:>5",
    "mcp youtube api stars:>5",
    "mcp gmail stars:>5",
    "mcp google-drive stars:>5",
    "mcp dropbox stars:>5",
    "mcp onedrive stars:>5",
    "mcp azure integration stars:>5",
    "mcp gcp integration stars:>5",
    "mcp openai integration stars:>5",
    "mcp anthropic integration stars:>5",
    # Narrow by function/domain
    "ai agent email tool stars:>10",
    "ai agent calendar tool stars:>10",
    "ai agent web browser stars:>20",
    "ai agent code tool stars:>30",
    "ai agent file tool stars:>10",
    "ai agent memory tool stars:>10",
    "ai agent document tool stars:>10",
    "ai agent api tool stars:>10",
    # OpenAI Assistants / tools ecosystem
    "openai assistant tool stars:>20",
    "gpt function calling stars:>30",
    "gpt tool plugin stars:>20",
    # Tool collections (catalog repos)
    "topic:mcp-tools",
    "topic:agent-tools",
    "topic:llm-tools",
    "topic:ai-tools",
    "ai-agent tool collection stars:>30",
]

# Categories mapped from GitHub topics / repo names
CATEGORY_MAP = {
    "search": ["search", "web-search", "google", "bing", "serp", "tavily", "brave"],
    "code-execution": ["code", "execute", "sandbox", "repl", "python", "javascript"],
    "file-system": ["file", "filesystem", "folder", "directory", "storage"],
    "database": ["database", "sql", "postgres", "mysql", "sqlite", "mongo", "redis"],
    "browser": ["browser", "playwright", "puppeteer", "selenium", "scraping", "crawl"],
    "communication": ["email", "gmail", "slack", "discord", "telegram", "sms", "notify"],
    "calendar": ["calendar", "schedule", "gcal", "outlook", "event"],
    "productivity": ["notion", "obsidian", "todoist", "linear", "jira", "trello"],
    "github": ["github", "gitlab", "git", "repo", "commit", "pr"],
    "data-processing": ["data", "csv", "json", "xml", "transform", "etl", "pandas"],
    "ai-ml": ["llm", "embedding", "vector", "rag", "openai", "anthropic", "huggingface"],
    "security": ["security", "vulnerability", "scan", "auth", "oauth"],
    "devops": ["docker", "kubernetes", "ci-cd", "deploy", "aws", "gcp", "azure"],
    "media": ["image", "video", "audio", "screenshot", "ocr", "pdf"],
    "knowledge": ["wikipedia", "arxiv", "pubmed", "news", "rss", "docs"],
    "finance": ["finance", "stock", "crypto", "payment", "stripe"],
    "maps": ["map", "geo", "location", "place", "weather"],
}

# ---------------------------------------------------------------------------
# GitHub API Client
# ---------------------------------------------------------------------------

def gh_request(path: str, params: dict = {}) -> dict:
    """Make a GitHub API request with auth and rate-limit handling."""
    url = f"{GITHUB_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ServAgent-Crawler/1.0",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            if remaining != "?" and int(remaining) < 5:
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(0, reset - int(time.time())) + 2
                print(f"  [rate-limit] Sleeping {wait}s...")
                time.sleep(wait)
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  [rate-limit 403] Sleeping 60s...")
            time.sleep(60)
            return {}
        if e.code == 422:
            return {}  # Invalid query
        print(f"  [HTTP {e.code}] {path}")
        return {}
    except Exception as e:
        print(f"  [error] {e}")
        return {}


def search_repos(query: str, max_pages: int = 5) -> list[dict]:
    """Search GitHub repos, return list of repo metadata."""
    repos = []
    for page in range(1, max_pages + 1):
        data = gh_request("/search/repositories", {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": 100,
            "page": page,
        })
        items = data.get("items", [])
        if not items:
            break
        repos.extend(items)
        total = data.get("total_count", 0)
        print(f"    page {page}: {len(items)} repos (total={total})")
        if len(repos) >= total or len(items) < 100:
            break
        time.sleep(1)  # be respectful
    return repos


# ---------------------------------------------------------------------------
# Skill Extractor — parse repo into ServAgent Tool format
# ---------------------------------------------------------------------------

def detect_category(repo: dict) -> str:
    name = (repo.get("name") or "").lower()
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in repo.get("topics", [])]
    text = f"{name} {desc} {' '.join(topics)}"
    for cat, keywords in CATEGORY_MAP.items():
        if any(k in text for k in keywords):
            return cat
    return "general"


def detect_protocols(repo: dict) -> list[str]:
    topics = [t.lower() for t in repo.get("topics", [])]
    desc = (repo.get("description") or "").lower()
    text = f"{desc} {' '.join(topics)}"
    protocols = []
    if any(k in text for k in ["mcp", "modelcontextprotocol", "model-context-protocol"]):
        protocols.append("mcp")
    if any(k in text for k in ["openai", "function", "tool-call", "langchain"]):
        protocols.append("openai-functions")
    if any(k in text for k in ["langchain"]):
        if "langchain" not in protocols:
            protocols.append("langchain")
    if not protocols:
        protocols = ["openai-functions"]  # default assumption
    return protocols


def repo_to_skill(repo: dict) -> dict:
    """Convert a GitHub repo object to ServAgent Tool schema."""
    owner = repo["owner"]["login"]
    name = repo["name"]
    description = repo.get("description") or f"{name} - GitHub repository"
    stars = repo.get("stargazers_count", 0)
    updated = repo.get("updated_at", "2024-01-01T00:00:00Z")
    homepage = repo.get("homepage") or ""
    html_url = repo["html_url"]

    # Stable ID from owner/name
    skill_id = f"skill-gh-{hashlib.md5(f'{owner}/{name}'.encode()).hexdigest()[:8]}"

    return {
        "id": skill_id,
        "name": name,
        "description": description[:200],
        "version": "1.0.0",
        "category": detect_category(repo),
        "tags": repo.get("topics", [])[:10],
        "provider": {
            "name": owner,
            "url": html_url,
            "verified": False,
        },
        "parameters": [],  # populated later by deeper analysis
        "pricing": {"model": "free"},
        "endpoints": {
            "base": homepage or html_url,
            "docs": html_url,
        },
        "protocols": detect_protocols(repo),
        "source": "github",
        "github": {
            "owner": owner,
            "repo": name,
            "stars": stars,
            "url": html_url,
            "updated_at": updated,
            "topics": repo.get("topics", []),
            "language": repo.get("language") or "",
            "license": (repo.get("license") or {}).get("spdx_id") or "unknown",
        },
        "createdAt": repo.get("created_at", "2024-01-01T00:00:00Z"),
        "updatedAt": updated,
    }


# ---------------------------------------------------------------------------
# Scorer — 5-dimension quality score
# ---------------------------------------------------------------------------

def score_skill(skill: dict) -> dict:
    """Score a skill 0-100. Adds quality_score and quality_tier fields."""
    gh = skill.get("github", {})
    stars = gh.get("stars", 0)
    topics = gh.get("topics", [])
    license_ = gh.get("license", "unknown")
    updated = gh.get("updated_at", "2020-01-01T00:00:00Z")
    language = gh.get("language", "")

    # 1. Community (30%) — stars are the best signal
    if stars >= 1000:
        community = 95
    elif stars >= 500:
        community = 85
    elif stars >= 200:
        community = 75
    elif stars >= 100:
        community = 65
    elif stars >= 50:
        community = 55
    elif stars >= 20:
        community = 45
    elif stars >= 10:
        community = 35
    else:
        community = 20

    # 2. Recency (20%) — recently updated is better
    try:
        days_ago = (datetime.now(timezone.utc) - datetime.fromisoformat(updated.replace("Z", "+00:00"))).days
    except Exception:
        days_ago = 365
    if days_ago < 30:
        recency = 95
    elif days_ago < 90:
        recency = 80
    elif days_ago < 180:
        recency = 65
    elif days_ago < 365:
        recency = 50
    else:
        recency = 25

    # 3. Description quality (20%)
    desc = skill.get("description", "")
    if len(desc) > 100:
        doc_quality = 80
    elif len(desc) > 50:
        doc_quality = 60
    elif len(desc) > 20:
        doc_quality = 40
    else:
        doc_quality = 15

    # 4. Protocol coverage (15%)
    protocols = skill.get("protocols", [])
    protocol_score = min(100, len(protocols) * 30 + 10)

    # 5. Code health (15%) — has license, language, topics
    code_health = 0
    if license_ not in ("unknown", "NOASSERTION", ""):
        code_health += 40
    if language:
        code_health += 30
    if len(topics) >= 3:
        code_health += 30

    # Weighted total
    total = round(
        community * 0.30 +
        recency * 0.20 +
        doc_quality * 0.20 +
        protocol_score * 0.15 +
        code_health * 0.15
    )

    tier = "high" if total >= 65 else "medium" if total >= 45 else "low"

    skill["quality_score"] = total
    skill["quality_tier"] = tier
    skill["score_breakdown"] = {
        "community": community,
        "recency": recency,
        "doc_quality": doc_quality,
        "protocol_coverage": protocol_score,
        "code_health": code_health,
    }
    return skill


# ---------------------------------------------------------------------------
# Upload to ServAgent API
# ---------------------------------------------------------------------------

def upload_to_api(skills: list[dict], api_url: str, api_key: str = "") -> dict:
    """Batch upload skills to ServAgent API."""
    url = f"{api_url}/api/v1/tools/bulk-import"
    body = json.dumps({"tools": skills}).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ServAgent-Crawler/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Bypass system proxy for localhost to avoid 502 errors
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()
        return {"success": False, "error": f"HTTP {e.code}: {body_err[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cmd_crawl(args):
    """Crawl GitHub and save raw skill data."""
    print(f"\n🕷  Starting crawl (token={'yes' if GITHUB_TOKEN else 'NO — rate-limited to 10 req/min'})")
    print(f"   Queries: {len(SEARCH_QUERIES)} | min-stars: {args.min_stars} | max-repos: {args.max_repos}\n")

    seen_ids: set[str] = set()
    all_skills: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        print(f"[{i+1}/{len(SEARCH_QUERIES)}] Query: {query!r}")
        repos = search_repos(query, max_pages=3)
        new = 0
        for repo in repos:
            if repo.get("stargazers_count", 0) < args.min_stars:
                continue
            if repo.get("fork") and not args.include_forks:
                continue
            key = f"{repo['owner']['login']}/{repo['name']}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            skill = repo_to_skill(repo)
            all_skills.append(skill)
            new += 1
            if len(all_skills) >= args.max_repos:
                break
        print(f"   → {new} new skills (total: {len(all_skills)})")
        if len(all_skills) >= args.max_repos:
            print(f"\n  Reached max-repos={args.max_repos}, stopping crawl.")
            break
        time.sleep(1)

    print(f"\n✅ Crawl complete: {len(all_skills)} unique skills")
    with open(args.output, "w") as f:
        json.dump(all_skills, f, indent=2, ensure_ascii=False)
    print(f"   Saved to {args.output}")


def cmd_score(args):
    """Load raw skills, score them, and save."""
    print(f"\n🏆 Scoring skills from {args.input}...")
    with open(args.input) as f:
        skills = json.load(f)

    scored = [score_skill(s) for s in skills]
    scored.sort(key=lambda s: s["quality_score"], reverse=True)

    high = [s for s in scored if s["quality_tier"] == "high"]
    medium = [s for s in scored if s["quality_tier"] == "medium"]
    low = [s for s in scored if s["quality_tier"] == "low"]

    print(f"\n📊 Score distribution:")
    print(f"   High  (65+): {len(high):4d} skills")
    print(f"   Medium(45-64): {len(medium):4d} skills")
    print(f"   Low   (<45): {len(low):4d} skills — will be excluded")
    print(f"   Total kept: {len(high) + len(medium)}")

    kept = high + medium  # filter out low
    with open(args.output, "w") as f:
        json.dump(kept, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Scored skills saved to {args.output}")

    # Summary stats
    if kept:
        avg = sum(s["quality_score"] for s in kept) / len(kept)
        top10 = kept[:10]
        print(f"\n🏅 Top 10 skills:")
        for s in top10:
            gh = s.get("github", {})
            print(f"   {s['quality_score']:3d} ⭐{gh.get('stars',0):5d}  {s['name']:<40} [{s['category']}]")
        print(f"\n   Average score: {avg:.1f}")


def _norm_name(name: str) -> str:
    """Normalize tool name for duplicate detection."""
    name = name.lower().strip()
    for suf in [
        "-mcp-server", "-mcp", "-server", "-tool", "-skill", "-plugin",
        "-py", "-ts", "-js", "-nodejs", "-python", "-go", "-rust", "-java",
        "-cli", "-sdk", "-api", "-client", "-lib",
    ]:
        if name.endswith(suf):
            name = name[:-len(suf)]
    name = re.sub(r"[-_.\s]+", "-", name).strip("-")
    return name


def _desc_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of significant word sets (>3 chars, alphabetic)."""
    def tokens(s):
        return set(w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in {
            "this", "that", "with", "from", "your", "will", "which", "their",
            "have", "more", "tool", "server", "model", "context", "protocol",
            "support", "using", "allows", "enable", "provides",
        })
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def dedup_skills(skills: list[dict]) -> tuple[list[dict], dict]:
    """
    Deduplicate skills by functionality. Three strategies (in priority order):
    1. Same GitHub URL → exact same repo, keep highest quality_score
    2. Same (norm_name, category) → same tool, different packaging
    3. Same category + description Jaccard ≥ 0.65 → functionally identical
    Returns (deduped_list, stats).
    """
    # Sort descending by quality_score so we always keep the best one first
    skills = sorted(skills, key=lambda s: s.get("quality_score", 0), reverse=True)

    kept: list[dict] = []
    seen_github_url: dict[str, int] = {}   # url → index in kept
    seen_name_cat: dict[tuple, int] = {}   # (norm_name, category) → index
    removed = 0
    reasons: list[str] = []

    for skill in skills:
        gh_url = skill.get("github", {}).get("url", "").strip()
        nname = _norm_name(skill.get("name", ""))
        category = skill.get("category", "")
        desc = skill.get("description", "")

        # Strategy 1: exact same GitHub repo URL
        if gh_url and gh_url in seen_github_url:
            existing = kept[seen_github_url[gh_url]]
            reasons.append(
                f"github-url | {skill['name']} ({skill.get('quality_score',0)}) "
                f"→ kept {existing['name']} ({existing.get('quality_score',0)})"
            )
            removed += 1
            continue

        # Strategy 2: same normalized name + same category
        key2 = (nname, category)
        if nname and key2 in seen_name_cat:
            existing = kept[seen_name_cat[key2]]
            reasons.append(
                f"name+cat  | {skill['name']} ({skill.get('quality_score',0)}) "
                f"→ kept {existing['name']} ({existing.get('quality_score',0)})"
            )
            removed += 1
            continue

        # Strategy 3: same category + very high description similarity
        # Threshold 0.72 avoids false positives for similar-but-different tools (e.g. SDKs in diff languages)
        if desc and category:
            dup_found = False
            for idx, candidate in enumerate(kept):
                if candidate.get("category") != category:
                    continue
                if _desc_jaccard(desc, candidate.get("description", "")) >= 0.72:
                    existing = kept[idx]
                    reasons.append(
                        f"desc-sim  | {skill['name']} ({skill.get('quality_score',0)}) "
                        f"→ kept {existing['name']} ({existing.get('quality_score',0)})"
                    )
                    removed += 1
                    dup_found = True
                    break
            if dup_found:
                continue

        # Not a duplicate — register and keep
        idx = len(kept)
        if gh_url:
            seen_github_url[gh_url] = idx
        if nname:
            seen_name_cat[(nname, category)] = idx
        kept.append(skill)

    stats = {
        "before": len(skills) + removed,  # already includes removed since we sorted first
        "after": len(kept),
        "removed": removed,
        "reasons": reasons[:50],   # cap log output
    }
    # Fix: before is len(skills) since we already sorted the full input
    stats["before"] = len(skills)
    return kept, stats


def cmd_dedup(args):
    """Deduplicate scored skills by functionality."""
    print(f"\n🔁 Deduplicating {args.input}...")
    with open(args.input) as f:
        skills = json.load(f)

    deduped, stats = dedup_skills(skills)

    print(f"\n📊 Dedup results:")
    print(f"   Before : {stats['before']:4d} skills")
    print(f"   Removed: {stats['removed']:4d} duplicates")
    print(f"   After  : {stats['after']:4d} skills")

    if stats["reasons"]:
        print(f"\n🗑  Sample removed (showing up to 20):")
        for r in stats["reasons"][:20]:
            print(f"   {r}")

    with open(args.output, "w") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Deduped skills saved to {args.output}")


def cmd_upload(args):
    """Upload scored skills to ServAgent API."""
    print(f"\n☁️  Uploading to {args.api_url}...")
    with open(args.input) as f:
        skills = json.load(f)

    # Upload in batches of 100
    batch_size = 100
    total_uploaded = 0
    for i in range(0, len(skills), batch_size):
        batch = skills[i:i + batch_size]
        result = upload_to_api(batch, args.api_url, args.api_key or "")
        if result.get("success"):
            total_uploaded += len(batch)
            print(f"   Batch {i//batch_size + 1}: ✓ {len(batch)} uploaded")
        else:
            print(f"   Batch {i//batch_size + 1}: ✗ {result.get('error')}")
        time.sleep(0.5)

    print(f"\n✅ Upload complete: {total_uploaded}/{len(skills)} skills")


def main():
    parser = argparse.ArgumentParser(description="ServAgent Skill Crawler")
    sub = parser.add_subparsers(dest="command")

    # crawl
    p_crawl = sub.add_parser("crawl", help="Crawl GitHub for skills")
    p_crawl.add_argument("--output", default="scripts/crawler/skills-raw.json")
    p_crawl.add_argument("--min-stars", type=int, default=10)
    p_crawl.add_argument("--max-repos", type=int, default=5000)
    p_crawl.add_argument("--include-forks", action="store_true")

    # score
    p_score = sub.add_parser("score", help="Score and filter skills")
    p_score.add_argument("--input", default="scripts/crawler/skills-raw.json")
    p_score.add_argument("--output", default="scripts/crawler/skills-scored.json")

    # dedup
    p_dedup = sub.add_parser("dedup", help="Deduplicate skills by functionality (keep highest quality)")
    p_dedup.add_argument("--input", default="scripts/crawler/skills-scored.json")
    p_dedup.add_argument("--output", default="scripts/crawler/skills-deduped.json")

    # upload
    p_upload = sub.add_parser("upload", help="Upload skills to ServAgent API")
    p_upload.add_argument("--input", default="scripts/crawler/skills-scored.json")
    p_upload.add_argument("--api-url", default="http://localhost:8787")
    p_upload.add_argument("--api-key", default="")

    # all-in-one
    p_run = sub.add_parser("run-all", help="Crawl → Score → Upload pipeline")
    p_run.add_argument("--min-stars", type=int, default=10)
    p_run.add_argument("--max-repos", type=int, default=5000)
    p_run.add_argument("--api-url", default="http://localhost:8787")
    p_run.add_argument("--api-key", default="")
    p_run.add_argument("--include-forks", action="store_true")

    args = parser.parse_args()

    if args.command == "crawl":
        cmd_crawl(args)
    elif args.command == "score":
        cmd_score(args)
    elif args.command == "dedup":
        cmd_dedup(args)
    elif args.command == "upload":
        cmd_upload(args)
    elif args.command == "run-all":
        args.output = "scripts/crawler/skills-raw.json"
        cmd_crawl(args)
        args.input = "scripts/crawler/skills-raw.json"
        args.output = "scripts/crawler/skills-scored.json"
        cmd_score(args)
        args.input = "scripts/crawler/skills-scored.json"
        args.output = "scripts/crawler/skills-deduped.json"
        cmd_dedup(args)
        args.input = "scripts/crawler/skills-deduped.json"
        cmd_upload(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
