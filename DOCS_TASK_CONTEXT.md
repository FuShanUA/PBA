# Docs 补全任务上下文

## 项目概述
Palantir 博客归档项目（FuShanUA/PBA），聚合 Palantir 官网博客、网站页面、文档内容，提供中英文双语浏览。

## 当前状态（2026-07-11）

### 已完成
- **Blog**: 355 篇，已翻译
- **Website**: 430 篇，已翻译
- **Docs**: 2462 页已抓取英文原文，2462 页已全部翻译成中文（100%）
  - Foundry: 1416 页（含 619 页补抓 + 原有 797 页）
  - Apollo: 204 页
  - Gotham: 9 页
  - 导航树: data/docs_nav_tree.json（1629 页完整导航树）
- 文件结构: `content/docs/{slug}/page.html`（英文）+ `page_zh.html`（中文）+ `meta.json`（URL元数据）
- 数据管线: `gen_docs_json.py` → `data/sources/docs.json` → `build.py` → `data/index.json`
- 前端: `index.html` 通过 `fetch('data/index.json')` 加载，支持 Blog/Website/Docs 三个来源切换
- 索引: data/index.json 共 3247 篇（blog 355 + docs 2462 + website 430）

### 翻译详情
- 小页面（<200KB）: 用 translate_one.py，qwen-turbo，150 词/chunk，60s deadline
- 大页面（>200KB）: 用 translate_big.py，qwen-turbo，排除代码块后翻译
  - 规则: <pre>/<code> 不翻译，类型名加括号中文如 Float（浮点），专有名词不翻译如 TypeScript
  - 9 个超大页面全部 100% 翻译完成

### 待办
1. **UI 改造**: docs 用卡片展示，应该改成模仿官网的侧边栏导航树 + 正文阅读区
2. **小页面重翻**: 387 页用旧规则翻译（无代码块排除），如需统一可重跑

## 关键文件

| 文件 | 用途 |
|------|------|
| `scrapers/rescrape.py` | 重新抓取缺失英文页面（wait_for_selector 修复 Next.js SSR） |
| `scrapers/translate_one.py` | 单页翻译脚本，xargs -P 并行调用 |
| `scrapers/translate_big.py` | 超大页面翻译，排除代码块，1hr deadline |
| `scrapers/translate_parallel.py` | ThreadPoolExecutor 并行翻译（备用） |
| `gen_docs_json.py` | 从 content/docs/ 生成 data/sources/docs.json |
| `build.py` | 合并所有 data/sources/*.json 到 data/index.json |
| `data/docs_nav_tree.json` | 完整导航树（1629 页） |
| `index.html` | 前端应用，fetch data/index.json |

## API 配置
- Provider: DashScope（百炼）
- Model: qwen-turbo（glm-5.2 对长内容超时，已弃用）
- API Key: /Users/shanfu/cc/.env 中 DASHSCOPE_API_KEY

## Git
- Remote: https://github.com/FuShanUA/PBA.git
- Branch: main
- GitHub Pages: https://fushanua.github.io/PBA/
- 最新提交: 6217b697 Re-translate 9 big docs pages with code-block exclusion
