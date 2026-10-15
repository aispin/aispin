# 技术要点

本文档介绍本仓库（GitHub Profile README 自动化生成器）的核心实现，对应脚本 [`build_readme.py`](../build_readme.py)。

## 整体架构

```
GitHub Actions (每 6 小时 cron / push / 手动触发)
        │
        ▼
build_readme.py
        ├── GitHub GraphQL API ──► 贡献数 / 仓库列表 / 语言字节 / Releases
        ├── 网易云音乐 Web API ──► 艺人专辑 → 歌曲（最近 10 首）
        │
        ├── assets/coding_activity.svg   ◄─ 脚本生成
        └── README.md / README.zh-CN.md  ◄─ 占位符回填
```

核心思路是 **占位符回填**：README 中预置 `<!-- xxx starts --><!-- xxx ends -->` 标记，脚本用正则替换标记之间的内容，只更新数据区，不碰手写的简介和静态部分。这保证了脚本幂等——重复运行不会产生重复内容。

```python
def replace_chunk(content, marker, chunk, inline=False):
    pattern = re.compile(r"<!-- {} starts -->.*?<!-- {} ends -->".format(marker, marker), re.DOTALL)
    chunk = "<!-- {} starts -->{}<!-- {} ends -->".format(marker, chunk, marker)
    return pattern.sub(chunk, content, count=1)
```

## Coding Activity：语言统计 SVG

### 数据来源

GitHub GraphQL `viewer` 一次查询拿到三样东西：

- `contributionsCollection.contributionCalendar.totalContributions` — 年度贡献数
- `repositories`（分页遍历全部公开仓库）— 每个仓库的 `languages(first: 10)` 返回语言字节数
- `releases(last: 1)` — 用于 Product Releases 区块

语言聚合：把所有仓库的同名语言字节数求和，取 Top 6，按占比渲染。

### SVG 生成

纯字符串拼接生成 SVG，无第三方图表库：

- 卡片背景固定 `#0d1117`（GitHub 暗色主题底色），明暗主题下都成立
- 每种语言一行：语言名 + 圆角进度条（背景槽 `#21262d` + 彩色填充）+ 百分比右对齐
- 颜色板取 GitHub 官方语言色系（`#58a6ff` 蓝、`#f1e05a` 黄、`#e34c26` 橙……）
- 文字用固定色 `#e6edf3` / `#8b949e`，**不用 `currentColor`** —— GitHub 的 `<img>` 标签不会继承文档颜色，`currentColor` 会退化为黑色，暗色主题下文字隐形（踩过的坑）

### 引用方式

```html
<a href="assets/coding_activity.svg" style="display:block"><img src="assets/coding_activity.svg" style="width:100%" alt="coding activity"></a>
<p align="center"><b>1,850</b> contributions in the last year</p>
```

- GitHub 的 sanitizer **允许 `<img>` 的 `style` 属性**，所以 `width:100%` 生效，图片撑满容器
- `<table>` 的 `style` 会被剥掉，表格想撑满只能靠 `<td width>` 属性（GitHub 的 `.markdown-body table { width: max-content }` 内置 CSS 无法覆盖）
- 贡献数用 `<p align="center">` 居中

## 网易云音乐：最近 10 首（免登录）

网易云 Web API 是公开的，无需登录、无需 key，带浏览器 UA 即可调用：

### 两步获取

**第一步**：艺人专辑列表（按发布时间倒序）

```
GET https://music.163.com/api/artist/albums/{artist_id}
```

**第二步**：逐个拉专辑详情，收集歌曲直到凑满 10 首

```
GET https://music.163.com/api/v1/album/{album_id}
```

```python
albums = sorted(resp.json()["hotAlbums"], key=lambda a: a["publishTime"], reverse=True)
for album in albums:
    detail = httpx.get(f"https://music.163.com/api/v1/album/{album['id']}", ...).json()
    for s in detail["songs"]:
        ...
```

### 为什么用歌曲页链接而不是 MP3 直链

网易云的 `song/enhance/player/url` 接口**不登录也能返回 320kbps MP3 直链**，但 URL 带 `expi: 1200`——**20 分钟过期**。写进 README 几小时后就是死链。所以卡片链接指向 `https://music.163.com/song?id={id}`，永久有效、可直接在线试听。

### 卡片渲染

GitHub 剥掉 `div` 的 `style`，flex 布局做不了。卡片墙用 **shields.io 徽章**实现：

```markdown
[![](https://img.shields.io/badge/{序号. 歌名(urlencode)}-{颜色}?style=flat-square&labelColor=0d1117)](https://music.163.com/song?id={id})
```

- `labelColor=0d1117` 与暗色卡片统一
- 6 色循环，视觉有节奏
- 中文/特殊字符 URL 编码（`urllib.parse.quote`），shields.io 正常渲染

## AI Projects 区块

GraphQL 拉回的仓库列表里过滤 `iskill-` / `ai-` 前缀，按 `pushedAt` 倒序取 5 个，渲染成 HTML 表格（Project / Description / Language）。描述里的 `|` 和换行需要转义，防止破坏表格结构。

## CI（GitHub Actions）

```yaml
schedule:
  - cron: '0 */6 * * *'    # 每 6 小时
push / workflow_dispatch        # push 和手动触发
```

要点：

- **Node.js 26**（`actions/setup-node@v4`）——旧行 workflow 里的 Node 20 已被 GitHub 标记 deprecated
- Python 3.13 + pip 缓存（key 绑定 `requirements.txt` hash）
- `GH_TOKEN` 来自仓库 secrets，脚本里 token 失效时静默降级（区块留空不报错）
- commit 用 bot 身份，`git commit ... || exit 0` 无变更时正常退出

## 踩坑记录

| 坑 | 原因 | 解法 |
|----|------|------|
| SVG 文字暗色主题下隐形 | `<img>` 不继承 `currentColor` | SVG 内固定颜色 |
| 表格 style 被剥 | GitHub sanitizer 白名单 | `<td width>` 属性 |
| 表格撑不满容器 | `table { width: max-content }` | 接受默认宽度 / 换徽章卡片 |
| MP3 直链失效 | 网易云 URL 20 分钟过期 | 链接歌曲页 |
| workflow 被 disabled | 60 天无活动自动禁用 | Actions 页手动 Enable |
| `.env` 里的 token | 本地明文，曾误判已入库 | 实际从未提交（gitignore 生效），仍建议轮换 |
