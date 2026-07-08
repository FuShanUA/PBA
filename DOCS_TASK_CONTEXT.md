# Docs 补全任务上下文

## 项目概述
Palantir 博客归档项目（FuShanUA/PBA），聚合 Palantir 官网博客、网站页面、文档内容，提供中英文双语浏览。

## 当前状态（2026-07-08）

### 已完成
- **Blog**: 355 篇，已翻译
- **Website**: 196 篇，已翻译
- **Docs (Foundry)**: 1655 页已抓取英文原文，1654 页已用 GLM-5.2 翻译成中文
- 文件结构: `content/docs/{slug}/page.html`（英文）+ `page_zh.html`（中文）+ `meta.json`（URL元数据）
- 数据管线: `gen_docs_json.py` → `data/sources/docs.json` → `build.py` → `data/index.json`
- 前端: `index.html` 通过 `fetch('data/index.json')` 加载，支持 Blog/Website/Docs 三个来源切换

### 问题
1. **只抓了 Foundry**: 之前用中文 sitemap（`/docs/zh/`）反推英文 URL，但中文版只翻译了 Foundry，导致 Apollo 和 Gotham 完全缺失
2. **Foundry 也不完整**: 中文侧边栏和英文侧边栏不一致，约 619 个英文 Foundry 页面被遗漏
3. **UI 不合适**: docs 用卡片展示，应该改成模仿官网的侧边栏导航树 + 正文阅读区

### 完整页面列表
已从官网导航树提取完整英文页面列表，保存在 `/tmp/docs_all_pages.json`（1629 页）:
- Foundry: 1416 页（已有 797 个，缺 619 个）
- Apollo: 204 页（全缺）
- Gotham: 9 页（全缺）
- 总计缺失: 832 页

**注意**: `/tmp/docs_all_pages.json` 在 /tmp 可能被清理。如果没有，需要重新运行导航树提取脚本（见下方"重新提取导航树"）。

## 需要完成的工作

### 1. 补抓缺失的 832 个英文页面
- URL 来源: 用 `/tmp/docs_all_pages.json`（完整导航树）替换 sitemap 作为 URL 来源
- 抓取脚本: `scrapers/scrape_docs.py --scrape`
- 内容选择器: `div.ptcom-design__markdownDoc__1uarhel`
- 需要修改脚本的 `parse_sitemap()` 函数，改为从 `docs_all_pages.json` 读取 URL 列表

### 2. 翻译新增页面
- 翻译脚本: `scrapers/scrape_docs.py --translate`
- 使用 GLM-5.2 via DashScope（百炼）
- 分块翻译，MAX_WORDS_PER_CHUNK=400
- >200KB 的超大页面暂时跳过

### 3. 重新生成索引
```bash
python3 gen_docs_json.py
python3 build.py
```

### 4. 改造 docs UI
- 从卡片改成模仿官网的侧边栏导航树 + 正文阅读区
- 导航树数据来源: `sidebarNavProps`（在页面 `__NEXT_DATA__` 的 `pageProps` 里）
- 结构: `items[]` → 每个 item 有 `link.url`, `link.text`, 嵌套 `items[]`

## 关键文件

| 文件 | 用途 |
|------|------|
| `scrapers/scrape_docs.py` | 抓取+翻译脚本，`--scrape` 和 `--translate` 两个独立阶段 |
| `gen_docs_json.py` | 从 content/docs/ 生成 data/sources/docs.json |
| `build.py` | 合并所有 data/sources/*.json 到 data/index.json |
| `incremental_scan.py` | 增量扫描新内容（blog/website/docs），支持 `--push` 自动推送 |
| `data/docs_sitemap.xml` | 完整 sitemap（5000 URL，含 zh/jp/kr） |
| `index.html` | 前端应用，fetch data/index.json |
| `AGENTS.md` | 项目规则（截图限制、大文件处理等） |

## 翻译依赖

翻译脚本依赖本地 postfdry 工具:
```
POSTFDRY = "/Users/shanfu/cc/Library/Tools/postfdry"
COMMON = "/Users/shanfu/cc/Library/Tools/common"
```
- `llm_utils.py`: GLM-5.2 API 调用，DashScope provider
- `translator_agent.py`: 翻译 prompt 构建，术语表（53 对）
- 术语表: `/Users/shanfu/cc/Library/Tools/postfdry/config/terms.yml`

**云环境配置**: 需要将 postfdry 工具复制到 repo 里，或设置环境变量 `DASHSCOPE_API_KEY` 并改用直接 API 调用。

## API 配置
- Provider: DashScope（百炼）
- Model: glm-5.2
- API Key: 在本地 .env 或环境变量中
- 限流: 分钟级 token 限制（TPM），429 是临时的，等几秒恢复
- fallback=False: 不自动切换到其他模型

## 运行方式

### 本地（用 screen 持久化）
```bash
cd /Users/shanfu/Desktop/palantir-blog-archive
# 抓取
screen -dmS docsscrape bash -c 'python3 -u scrapers/scrape_docs.py --scrape 2>&1 | tee /tmp/docs_scrape.log'
# 翻译
screen -dmS docstranslate bash -c 'python3 -u scrapers/scrape_docs.py --translate 2>&1 | tee /tmp/docs_translate.log'
```

### 重新提取导航树
如果 `/tmp/docs_all_pages.json` 不存在:
```python
# 脚本在 /tmp/docs_sidebar_full.py
# 需要访问 palantir.com/docs，用 Playwright 提取 sidebarNavProps
# 提取每个 section overview 页面的 __NEXT_DATA__.pageProps.sidebarNavProps.items
# URL 在 item.link.url，标题在 item.link.text
```

## Git
- Remote: https://github.com/FuShanUA/PBA.git
- Branch: main
- GitHub Pages: https://fushanua.github.io/PBA/
