# ServAgent Crawler

Crawls GitHub weekly for high-quality MCP servers, Claude skills, and agent tools.

## Flow

```
[Every Thursday 22:00 CST]
  crawler/crawl.yml
      ↓ crawl GitHub API
      ↓ score & filter (quality ≥ 45)
      ↓ dedup
      ↓ open PR → servagent-ai/skills-data
                      ↓ (review & merge)
                  skills-data/validate.yml
                      ↓ validate JSON
                      ↓ upload to https://servagent.ai
```

## Manual trigger

GitHub Actions → Crawl → Run workflow

Inputs:
- `max_repos` (default: 5000)
- `min_stars` (default: 10)

## Secrets required

| Secret | Description |
|--------|-------------|
| `SKILLS_DATA_TOKEN` | GitHub PAT with `repo` scope for servagent-ai/skills-data |
