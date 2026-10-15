import os
import re
import pathlib

import httpx

root = pathlib.Path(__file__).parent.resolve()
GH_TOKEN = os.environ.get("GH_TOKEN", "")
NETEASE_ARTIST_ID = "49232788"
PROJECT_PREFIXES = ("iskill-", "ai-")
AI_PROJECTS_LIMIT = 20
MUSIC_LIMIT = 10

QUERY = """
query($after: String) {
  viewer {
    login
    contributionsCollection { contributionCalendar { totalContributions } }
    repositories(first: 100, privacy: PUBLIC, isFork: false, ownerAffiliations: OWNER, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name url description pushedAt
        primaryLanguage { name color }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
        releases(last: 1, orderBy: {field: CREATED_AT, direction: DESC}) { totalCount nodes { name publishedAt url } }
      }
    }
  }
}
"""


def replace_chunk(content, marker, chunk, inline=False):
    pattern = re.compile(r"<!-- {} starts -->.*?<!-- {} ends -->".format(marker, marker), re.DOTALL)
    if not inline:
        chunk = "\n{}\n".format(chunk)
    chunk = "<!-- {} starts -->{}<!-- {} ends -->".format(marker, chunk, marker)
    return pattern.sub(chunk, content, count=1)


def gh_graphql(query, token, **variables):
    resp = httpx.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables or None},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def fetch_viewer_data(token):
    login, total_contributions, repos, releases = "aispin", 0, [], []
    after = None
    while True:
        data = gh_graphql(QUERY, token, after=after)
        viewer = data["viewer"]
        login = viewer["login"]
        total_contributions = viewer["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        page = viewer["repositories"]
        repos.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    for repo in repos:
        r = repo.get("releases") or {}
        if r.get("totalCount") and r.get("nodes"):
            rel = r["nodes"][0]
            releases.append({
                "repo": repo["name"], "repo_url": repo["url"],
                "release": (rel["name"] or "").replace(repo["name"], "").strip(),
                "published_at": rel["publishedAt"][:10], "url": rel["url"],
            })
    releases.sort(key=lambda r: r["published_at"], reverse=True)
    return login, total_contributions, repos, releases


def fetch_netease_songs(artist_id, limit=10):
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = httpx.get(f"https://music.163.com/api/artist/albums/{artist_id}", headers=headers, timeout=15)
    resp.raise_for_status()
    albums = sorted(resp.json()["hotAlbums"], key=lambda a: a["publishTime"], reverse=True)
    songs, seen = [], set()
    for album in albums:
        if len(songs) >= limit:
            break
        detail = httpx.get(f"https://music.163.com/api/v1/album/{album['id']}", headers=headers, timeout=15).json()
        for s in detail.get("songs", []):
            if s["id"] not in seen:
                songs.append({"id": s["id"], "name": s["name"], "album": album["name"]})
                seen.add(s["id"])
    return songs[:limit]


def format_language_table(repos, bar_width=25, zh=False):
    lang_bytes = {}
    for repo in repos:
        for edge in (repo.get("languages") or {}).get("edges") or []:
            name = edge["node"]["name"]
            lang_bytes[name] = lang_bytes.get(name, 0) + edge["size"]
    if not lang_bytes:
        return ""
    total = sum(lang_bytes.values())
    top = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)[:8]
    h1, h2 = ("语言", "占比") if zh else ("Language", "Share")
    lines = [f"| {h1} | {h2} |", "|----------|-------|"]
    for name, size in top:
        pct = size / total * 100
        filled = round(pct / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        lines.append(f"| {name} | `{bar}` {pct:.1f}% |")
    return "\n".join(lines)


def format_ai_projects(repos, zh=False):
    projects = sorted(
        (r for r in repos if r["name"].startswith(PROJECT_PREFIXES)),
        key=lambda r: r["pushedAt"], reverse=True,
    )[:AI_PROJECTS_LIMIT]
    if not projects:
        return ""
    h1, h2, h3 = ("项目", "描述", "语言") if zh else ("Project", "Description", "Language")
    lines = [f"| {h1} | {h2} | {h3} |", "|---------|-------------|----------|"]
    for p in projects:
        desc = (p.get("description") or "—").replace("|", "\\|").replace("\n", " ")
        lang = (p.get("primaryLanguage") or {}).get("name") or "—"
        lines.append(f"| [{p['name']}]({p['url']}) | {desc} | {lang} |")
    return "\n".join(lines)


def format_music(songs, zh=False):
    if not songs:
        return ""
    h1, h2, h3 = ("#", "歌名", "专辑") if zh else ("#", "Title", "Album")
    lines = [f"| {h1} | {h2} | {h3} |", f"|---|-------|-------|"]
    for i, s in enumerate(songs, 1):
        lines.append(f"| {i} | [{s['name']}](https://music.163.com/song?id={s['id']}) | {s['album']} |")
    return "\n".join(lines)


def format_releases(releases, limit=5):
    return "\n".join(
        "* [{repo}]({repo_url}): [{release}]({url}) - {published_at}".format(**r)
        for r in releases[:limit]
    )


def update_readme(path, lang_md, contributions, projects_md, music_md, zh=False):
    content = path.read_text()
    if contributions:
        text = f"过去一年 **{contributions:,}** 次贡献" if zh else f"**{contributions:,}** contributions in the last year"
        content = replace_chunk(content, "contributions", text, inline=True)
    if lang_md:
        content = replace_chunk(content, "coding_activity", lang_md)
    if projects_md:
        content = replace_chunk(content, "ai_projects", projects_md)
    if music_md:
        content = replace_chunk(content, "latest_music", music_md)
    path.write_text(content)


def update_releases(path, releases):
    content = path.read_text()
    content = replace_chunk(content, "recent_releases", format_releases(releases))
    content = replace_chunk(content, "release_count", str(len(releases)), inline=True)
    path.write_text(content)


def main():
    token = GH_TOKEN
    login, total_contributions, repos, releases = "aispin", 0, [], []

    if token:
        try:
            login, total_contributions, repos, releases = fetch_viewer_data(token)
        except Exception as e:
            print(f"GitHub GraphQL error: {e}")

    try:
        songs = fetch_netease_songs(NETEASE_ARTIST_ID, MUSIC_LIMIT)
    except Exception as e:
        print(f"NetEase fetch error: {e}")
        songs = []

    lang_md = format_language_table(repos)
    projects_md = format_ai_projects(repos)
    music_md = format_music(songs)

    update_readme(root / "README.md", lang_md, total_contributions, projects_md, music_md)
    update_readme(root / "README.zh-CN.md", lang_md, total_contributions, projects_md, music_md, zh=True)

    if releases:
        update_releases(root / "releases.md", releases)


if __name__ == "__main__":
    main()
