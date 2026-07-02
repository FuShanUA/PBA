# Palantir 博客归档

Palantir 官方博客文章的中文归档浏览器，按 Palantir 真实 Medium 标签体系分类，包含 290 篇文章、6 个主分类及各自的二级子分类。

## 在线访问

通过 GitHub Pages 在线访问：

https://fushanua.github.io/PBA/

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

也可以直接用浏览器打开 `index.html`（自包含单文件，内联全部数据与脚本，无需后端）。

## 分类体系

| 主分类 | 文章数 | 二级子分类 |
|--------|--------|-----------|
| 工程与技术 | 160 | 软件工程、信息安全、Foundry 架构、前端工程、生产基础设施、软件供应链等 |
| 产品 | 103 | Foundry、AIP、Apollo、Ontology、ERP 软件、机器学习、RFX 博客系列 |
| 公司 | 66 | 合作伙伴、国防、医疗、供应链 |
| 隐私与公民自由 | 63 | 隐私、公共政策、AI 伦理、负责任 AI、Palantir 解读、FAQ |
| Palantir 全球 | 53 | 英国、德国、法国、日本、西班牙语 |
| 企业文化 | 32 | 企业文化、实习、招聘、团队、角色 |

## 项目结构

| 文件 | 说明 |
|------|------|
| `app.py` | Streamlit 包装，通过 iframe 嵌入 index.html |
| `index.html` | 自包含归档页面（内联数据 + JS） |
| `requirements.txt` | Python 依赖 |
| `rebuild_full.py` | 重建 index.html 的脚本（从原始数据生成） |
| `classified_articles.json` | 按标签分类的文章数据 |
| `page_data.json` | 页面渲染数据 |

## 部署到 Streamlit Community Cloud（可选）

1. 将本仓库推送到 GitHub
2. 前往 [share.streamlit.io](https://share.streamlit.io)
3. 点击 **New app**，选择 `FuShanUA/PBA` 仓库
4. 主文件路径填 `app.py`
5. 点击 **Deploy**
