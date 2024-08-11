from python_graphql_client import GraphqlClient
import feedparser
import pathlib
import re
import os
from datetime import datetime, timedelta

root = pathlib.Path(__file__).parent.resolve()
client = GraphqlClient(endpoint="https://api.github.com/graphql")

TOKEN = os.environ.get("GH_TOKEN", "")

def replace_chunk(content, marker, chunk, inline=False):
    r = re.compile(
        r"<!\-\- {} starts \-\->.*<!\-\- {} ends \-\->".format(marker, marker),
        re.DOTALL,
    )
    if not inline:
        chunk = "\n{}\n".format(chunk)
    chunk = "<!-- {} starts -->{}<!-- {} ends -->".format(marker, chunk, marker)
    return r.sub(chunk, content)

def formatGMTime(timestamp):
    GMT_FORMAT = "%a, %d %b %Y %H:%M:%S GMT"
    dateStr = datetime.strptime(timestamp, GMT_FORMAT) + timedelta(hours=8)
    return dateStr.strftime('%Y-%m-%d')

def repository_query(after_cursor=None):
    return """
query {
  viewer {
    repositories(first: 100, privacy: PUBLIC, isFork:false, ownerAffiliations:OWNER, after:AFTER) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        description
        url
        releases(last: 100, orderBy: { field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes {
            name
            publishedAt
            url
          }
        }
      }
    }
  }
}
""".replace(
        "AFTER", '"{}"'.format(after_cursor) if after_cursor else "null"
    )

def fetch_releases(oauth_token):
    repos = []
    releases = []
    repo_names = set()
    has_next_page = True
    after_cursor = None

    while has_next_page:
        try:
            data = client.execute(
                query=repository_query(after_cursor),
                headers={"Authorization": "Bearer {}".format(oauth_token)},
            )
        except Exception as e:
            print(f"Error fetching releases: {e}")
            break

        for repo in data["data"]["viewer"]["repositories"]["nodes"]:
            if repo["releases"]["totalCount"] and repo["name"] not in repo_names:
                repos.append(repo)
                repo_names.add(repo["name"])
                releases.append(
                    {
                        "repo": repo["name"],
                        "repo_url": repo["url"],
                        "description": repo["description"],
                        "release": repo["releases"]["nodes"][0]["name"]
                        .replace(repo["name"], "")
                        .strip(),
                        "published_at": repo["releases"]["nodes"][0][
                            "publishedAt"
                        ].split("T")[0],
                        "url": repo["releases"]["nodes"][0]["url"],
                    }
                )
        has_next_page = data["data"]["viewer"]["repositories"]["pageInfo"][
            "hasNextPage"
        ]
        after_cursor = data["data"]["viewer"]["repositories"]["pageInfo"]["endCursor"]
    return releases

def fetch_projects():
    content = feedparser.parse("https://huangyongyou.cn/proj.xml")["entries"]
    entries = [
        {
            "title": entry["title"],
            "url": entry["link"].split("#")[0],
            "published": formatGMTime(entry["published"]),
        }
        for entry in content
    ]
    return entries

def fetch_articles():
    content = feedparser.parse("https://huangyongyou.cn/rss.xml")["entries"]
    entries = [
        {
            "title": entry["title"],
            "url": entry["link"].split("#")[0],
            "published": formatGMTime(entry["published"]),
        }
        for entry in content
    ]
    return entries

def fetch_and_format_releases(token, limit=5):
    items_releases = fetch_releases(token)
    items_releases.sort(key=lambda r: r["published_at"], reverse=True)
    md_release = "\n".join(
        [
            "* <a href='{url}' target='_blank'>{repo} {release}</a> - {published_at}".format(
                **release
            )
            for release in items_releases[:limit]
        ]
    )
    return md_release, items_releases

def fetch_and_format_projects(limit=5):
    items_projects = fetch_projects()
    md_projects = "\n".join(
        [
            "* <a href='{url}' target='_blank'>{title}</a> - {published}".format(
                **entry
            )
            for entry in items_projects[:limit]
        ]
    )
    return md_projects

def fetch_and_format_articles(limit=5):
    items_articles = fetch_articles()
    md_articles = "\n".join(
        [
            "* <a href='{url}' target='_blank'>{title}</a> - {published}".format(
                **entry
            )
            for entry in items_articles[:limit]
        ]
    )
    return md_articles

def update_readme(readme_path, token):
    with readme_path.open() as f:
        readme_contents = f.read()

    md_release, items_releases = fetch_and_format_releases(token)
    readme_contents = replace_chunk(readme_contents, "recent_releases", md_release)

    md_projects = fetch_and_format_projects()
    readme_contents = replace_chunk(readme_contents, "recent_projects", md_projects)

    md_articles = fetch_and_format_articles()
    readme_contents = replace_chunk(readme_contents, "recent_articles", md_articles)

    with readme_path.open("w") as f:
        f.write(readme_contents)
    return items_releases

def update_project_releases(project_releases_path, items_releases):
    with project_releases_path.open() as f:
        project_releases_content = f.read()
    
    project_releases_md = "\n".join(
        [
            (
                "* **[{repo}]({repo_url})**: [{release}]({url}) - {published_at}\n"
                "<br>{description}"
            ).format(**release)
            for release in items_releases
        ]
    )
    
    project_releases_content = replace_chunk(
        project_releases_content, "recent_releases", project_releases_md
    )
    project_releases_content = replace_chunk(
        project_releases_content, "release_count", str(len(items_releases)), inline=True
    )
    
    with project_releases_path.open("w") as f:
        f.write(project_releases_content)

if __name__ == "__main__":
    readme_path = root / "README.md"
    project_releases_path = root / "releases.md"

    items_releases = update_readme(readme_path, TOKEN)
    update_project_releases(project_releases_path, items_releases)