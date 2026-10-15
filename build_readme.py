import os
import re
import pathlib
import urllib.parse

import httpx

root = pathlib.Path(__file__).parent.resolve()
GH_TOKEN = os.environ.get("GH_TOKEN", "")
NETEASE_ARTIST_ID = "49232788"
PROJECT_PREFIXES = ("iskill-", "ai-")
AI_PROJECTS_LIMIT = 5
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


def build_language_svg(repos):
    lang_bytes = {}
    for repo in repos:
        for edge in (repo.get("languages") or {}).get("edges") or []:
            name = edge["node"]["name"]
            lang_bytes[name] = lang_bytes.get(name, 0) + edge["size"]
    if not lang_bytes:
        return None
    total = sum(lang_bytes.values())
    top = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)[:6]
    palette = ["#58a6ff", "#f1e05a", "#e34c26", "#bc8cff", "#3fb950", "#39c5cf"]
    W = 800
    row_h = 34
    pad = 20
    height = pad * 2 + len(top) * row_h
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}">',
        f'  <rect width="{W}" height="{height}" rx="10" fill="#0d1117"/>',
    ]
    label_w = 150
    pct_w = 60
    bar_w = W - pad * 2 - label_w - pct_w
    for i, (name, size) in enumerate(top):
        y = pad + i * row_h
        pct = size / total * 100
        color = palette[i % len(palette)]
        svg.append(f'  <text x="{pad}" y="{y + 14}" font-family="Segoe UI,Helvetica,Arial,sans-serif" font-size="14" fill="#e6edf3">{name}</text>')
        svg.append(f'  <rect x="{pad + label_w}" y="{y + 4}" width="{bar_w}" height="10" rx="5" fill="#21262d"/>')
        svg.append(f'  <rect x="{pad + label_w}" y="{y + 4}" width="{max(round(pct / 100 * bar_w), 4)}" height="10" rx="5" fill="{color}"/>')
        svg.append(f'  <text x="{W - pad}" y="{y + 14}" font-family="Segoe UI,Helvetica,Arial,sans-serif" font-size="13" fill="#8b949e" text-anchor="end">{pct:.1f}%</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def format_ai_projects(repos, zh=False):
    projects = sorted(
        (r for r in repos if r["name"].startswith(PROJECT_PREFIXES)),
        key=lambda r: r["pushedAt"], reverse=True,
    )[:AI_PROJECTS_LIMIT]
    if not projects:
        return ""
    h1, h2, h3 = ("项目", "描述", "语言") if zh else ("Project", "Description", "Language")
    lines = ['<table>', f'<tr><th width="25%">{h1}</th><th>{h2}</th><th width="15%">{h3}</th></tr>']
    for p in projects:
        desc = (p.get("description") or "—").replace("|", "\\|").replace("\n", " ")
        lang = (p.get("primaryLanguage") or {}).get("name") or "—"
        lines.append(f'<tr><td width="25%"><a href="{p["url"]}">{p["name"]}</a></td><td>{desc}</td><td width="15%">{lang}</td></tr>')
    lines.append("</table>")
    return "\n".join(lines)


def format_music(songs, zh=False):
    if not songs:
        return ""
    colors = ["1f6feb", "238636", "8957e5", "bf3989", "d29922", "1b7f8c"]
    lines = []
    for i, s in enumerate(songs, 1):
        title = urllib.parse.quote(f"{i}. {s['name']}", safe="")
        album = urllib.parse.quote(f"💿 {s['album']}", safe="")
        color = colors[(i - 1) % len(colors)]
        card = (
            f'[![](https://img.shields.io/badge/{title}-{color}?style=flat-square&labelColor=0d1117)'
            f'](https://music.163.com/song?id={s["id"]}) '
            f'[![](https://img.shields.io/badge/{album}-30363d?style=flat-square&labelColor=21262d)]'
            f'(https://music.163.com/song?id={s["id"]})'
        )
        lines.append(card)
    return "\n".join(lines)


def format_releases(releases, limit=5):
    return "\n".join(
        "* [{repo}]({repo_url}): [{release}]({url}) - {published_at}".format(**r)
        for r in releases[:limit]
    )


def update_readme(path, lang_md, contributions, projects_md, music_md, zh=False):
    content = path.read_text()
    if lang_md:
        img = '<a href="assets/coding_activity.svg" style="display:block"><img src="assets/coding_activity.svg" style="width:100%" alt="coding activity"></a>'
        if contributions:
            text = f"过去一年 <b>{contributions:,}</b> 次贡献" if zh else f"<b>{contributions:,}</b> contributions in the last year"
            img += f'\n<p align="center">{text}</p>'
        content = replace_chunk(content, "coding_activity", img)
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

    lang_svg = build_language_svg(repos)
    if lang_svg:
        (root / "assets" / "coding_activity.svg").parent.mkdir(exist_ok=True)
        (root / "assets" / "coding_activity.svg").write_text(lang_svg)
    projects_md = format_ai_projects(repos)
    music_md = format_music(songs)

    update_readme(root / "README.md", lang_svg is not None, total_contributions, projects_md, music_md)
    update_readme(root / "README.zh-CN.md", lang_svg is not None, total_contributions, projects_md, music_md, zh=True)

    if releases:
        update_releases(root / "releases.md", releases)


if __name__ == "__main__":
    main()
