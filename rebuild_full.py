#!/usr/bin/env python3
"""Rebuild index.html with: translated titles, two-level categories, Chinese UI, day dates, default zh+light, pagination."""

import json

# Load data
with open('classified_articles.json') as f:
    articles = json.load(f)
with open('titles_zh.json') as f:
    titles_zh = json.load(f)

# Build article data array for JS
A = []
for i, a in enumerate(articles):
    tags = a.get('tags', {})
    A.append({
        "t": a['title'],
        "tt": titles_zh[i],
        "d": a.get('date', ''),
        "s": a['slug'],
        "u": a['url'],
        "bc": tags.get('blogCategory', []),
        "tc": tags.get('tech', []),
        "pc": tags.get('product', []),
        "ic": tags.get('industry', []),
        "th": a.get('thumbnail', ''),
        "ds": a.get('description', ''),
        "sn": a.get('snippet', ''),
        "hp": a.get('htmlPath', '')
    })

# Build tag counts
def count_tags(field):
    counts = {}
    for a in articles:
        tags = a.get('tags', {})
        for t in tags.get(field, []):
            counts[t] = counts.get(t, 0) + 1
    return counts

TC = {
    "blogCategory": count_tags('blogCategory'),
    "tc": count_tags('tech'),
    "pc": count_tags('product'),
    "industry": count_tags('industry')
}

# Build date tree
DT = {}
for a in A:
    d = a['d']
    if not d or len(d) < 7:
        continue
    y = d[:4]
    m = d[5:7]
    if y not in DT:
        DT[y] = {}
    DT[y][m] = DT[y].get(m, 0) + 1

# Chinese translations for categories/tags
TAG_ZH = {
    "Engineering & Tech": "工程与技术",
    "Product": "产品",
    "Privacy & Civil Liberties": "隐私与公民自由",
    "Palantir Global": "Palantir 全球",
    "AI/ML": "人工智能/机器学习",
    "Backend Eng": "后端工程",
    "Data Integration": "数据集成",
    "Eval": "评估",
    "Frontend Eng": "前端工程",
    "Git Internals": "Git 内部原理",
    "Infrastructure & DevOps": "基础设施与运维",
    "Ontology": "本体论",
    "Security": "安全",
    "AIP": "AIP", "Apollo": "Apollo", "ERP Suite": "ERP 套件",
    "FedStart": "FedStart", "Foundry": "Foundry", "Gotham": "Gotham",
    "Hyperauto": "Hyperauto", "OSDK": "OSDK",
    "Pipeline Builder": "Pipeline Builder", "Titan": "Titan",
    "Construction": "建筑业", "Defense & Intel": "国防与情报",
    "Energy": "能源", "Finance": "金融", "Government": "政府",
    "Healthcare": "医疗", "Manufacturing": "制造业"
}

# Category hierarchy: which sub-tags belong to which primary category
CAT_HIERARCHY = {
    "Engineering & Tech": "tech",
    "Product": "product"
}

A_JSON = json.dumps(A, ensure_ascii=False)
TC_JSON = json.dumps(TC, ensure_ascii=False)
DT_JSON = json.dumps(DT, ensure_ascii=False)
TAG_ZH_JSON = json.dumps(TAG_ZH, ensure_ascii=False)

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Palantir 博客归档</title>
<link rel="preconnect" href="https://fonts.googleapis.com" crossorigin>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" media="print" onload="this.media='all'">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/lxgw-wenkai-screen-webfont/style.css" media="print" onload="this.media='all'">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#F8FAFC;--card:#FFFFFF;--card-hover:#F1F5F9;--border:rgba(15,23,42,0.08);
  --text:#0F172A;--muted:#475569;--accent:#0EA5E9;--accent-soft:rgba(14,165,233,0.08);
  --sidebar-bg:#FFFFFF;--input-bg:#F1F5F9;--shadow:0 4px 24px rgba(0,0,0,0.06);
  --chip-bc:rgba(14,165,233,0.1);--chip-tc:rgba(139,92,246,0.1);--chip-pc:rgba(16,185,129,0.1);--chip-ic:rgba(249,115,22,0.1);
  --chip-bc-text:#0EA5E9;--chip-tc-text:#8B5CF6;--chip-pc-text:#10B981;--chip-ic-text:#F97316;
  --chip-bc-border:rgba(14,165,233,0.25);--chip-tc-border:rgba(139,92,246,0.25);--chip-pc-border:rgba(16,185,129,0.25);--chip-ic-border:rgba(249,115,22,0.25);
  --thumb-placeholder:#E2E8F0;--scrollbar-track:#F1F5F9;--scrollbar-thumb:#CBD5E1;
}
[data-theme="dark"]{
  --bg:#0F172A;--card:#1E293B;--card-hover:#334155;--border:rgba(255,255,255,0.08);
  --text:#F8FAFC;--muted:#94A3B8;--accent:#38BDF8;--accent-soft:rgba(56,189,248,0.12);
  --sidebar-bg:#1E293B;--input-bg:#0F172A;--shadow:0 4px 24px rgba(0,0,0,0.3);
  --chip-bc:rgba(56,189,248,0.15);--chip-tc:rgba(167,139,250,0.15);--chip-pc:rgba(52,211,153,0.15);--chip-ic:rgba(251,146,60,0.15);
  --chip-bc-text:#38BDF8;--chip-tc-text:#A78BFA;--chip-pc-text:#34D399;--chip-ic-text:#FB923C;
  --chip-bc-border:rgba(56,189,248,0.3);--chip-tc-border:rgba(167,139,250,0.3);--chip-pc-border:rgba(52,211,153,0.3);--chip-ic-border:rgba(251,146,60,0.3);
  --thumb-placeholder:#334155;--scrollbar-track:#0F172A;--scrollbar-thumb:#334155;
}
body{font-family:'Outfit','LXGW WenKai Screen','STKaiti','Kaiti SC',sans-serif;background:var(--bg);color:var(--text);line-height:1.6;transition:background 0.3s ease,color 0.3s ease}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--scrollbar-track)}::-webkit-scrollbar-thumb{background:var(--scrollbar-thumb);border-radius:3px}
header{background:var(--sidebar-bg);padding:16px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;backdrop-filter:blur(12px)}
header h1{font-size:1.35em;font-weight:700;color:var(--accent);letter-spacing:-0.5px}
.header-right{display:flex;align-items:center;gap:10px}
.toggle-group{display:flex;align-items:center;gap:4px;background:var(--input-bg);padding:4px 10px;border-radius:20px;border:1px solid var(--border)}
.toggle-group span{font-size:.8em;color:var(--muted);cursor:pointer;user-select:none;transition:color 0.2s;padding:2px 6px;border-radius:12px}
.toggle-group span.active{color:var(--accent);font-weight:600;background:var(--accent-soft)}
.toggle-group .sep{color:var(--border);cursor:default;padding:0}
.theme-btn{background:var(--input-bg);border:1px solid var(--border);border-radius:50%;width:34px;height:34px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:1.05em;color:var(--text);transition:all 0.2s}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}
.layout{display:flex;max-width:1700px;margin:0 auto}
.sidebar{width:260px;min-width:260px;border-right:1px solid var(--border);padding:16px 12px;position:sticky;top:57px;height:calc(100vh - 57px);overflow-y:auto;background:var(--bg)}
.acc-section{margin-bottom:4px}
.acc-header{display:flex;align-items:center;gap:8px;padding:9px 12px;border-radius:8px;cursor:pointer;font-size:.8em;font-weight:600;color:var(--text);background:var(--card);border:1px solid var(--border);transition:all 0.15s;user-select:none}
.acc-header:hover{border-color:var(--accent)}
.acc-arrow{display:inline-block;width:0;height:0;border-left:4px solid var(--muted);border-top:4px solid transparent;border-bottom:4px solid transparent;transition:transform 0.2s;flex-shrink:0}
.acc-section.open .acc-arrow{transform:rotate(90deg)}
.acc-title{flex:1}
.acc-count{font-size:.85em;color:var(--muted);font-weight:400}
.acc-body{max-height:0;overflow:hidden;transition:max-height 0.3s ease-out}
.acc-section.open .acc-body{max-height:800px}
.tag{display:flex;justify-content:space-between;align-items:center;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.82em;transition:all 0.12s;color:var(--text)}
.tag:hover{background:var(--card)}
.tag.active{background:var(--accent-soft);color:var(--accent);font-weight:500}
.tag .count{color:var(--muted);font-size:.82em}
.tag.active .count{color:var(--accent)}
.acc-tags{padding:4px 0 4px 10px}
.sub-section{margin:2px 0}
.sub-header{display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:6px;cursor:pointer;font-size:.78em;color:var(--muted);user-select:none;transition:color 0.15s}
.sub-header:hover{color:var(--text)}
.sub-arrow{display:inline-block;width:0;height:0;border-left:3px solid var(--muted);border-top:3px solid transparent;border-bottom:3px solid transparent;transition:transform 0.2s}
.sub-section.open .sub-arrow{transform:rotate(90deg)}
.sub-body{max-height:0;overflow:hidden;transition:max-height 0.25s ease-out}
.sub-section.open .sub-body{max-height:400px}
.sub-tags{padding:2px 0 2px 16px}
.sub-tags .tag{padding:3px 10px;font-size:.76em}
.main{flex:1;padding:20px 24px;min-width:0}
.toolbar{display:flex;gap:10px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
.search-wrap{flex:1;min-width:200px;position:relative}
.search-wrap input{width:100%;padding:10px 14px 10px 38px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:.92em;font-family:inherit;transition:border-color 0.2s}
.search-wrap input:focus{outline:none;border-color:var(--accent)}
.search-wrap .icon{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:1em}
.toolbar select{padding:8px 28px 8px 12px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:.84em;font-family:inherit;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' stroke='%2394A3B8' fill='none' stroke-width='1.5'/></svg>");background-repeat:no-repeat;background-position:right 8px center}
.toolbar select:focus{outline:none;border-color:var(--accent)}
.filter-btn{display:none;padding:8px 14px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:.84em;font-family:inherit;cursor:pointer;align-items:center;gap:6px}
.filter-btn:hover{border-color:var(--accent)}
.active-filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.chip{display:inline-flex;align-items:center;gap:4px;padding:4px 12px;border-radius:14px;font-size:.78em;cursor:pointer;transition:opacity 0.15s}
.chip:hover{opacity:0.8}
.chip.bc{background:var(--chip-bc);color:var(--chip-bc-text);border:1px solid var(--chip-bc-border)}
.chip.tc{background:var(--chip-tc);color:var(--chip-tc-text);border:1px solid var(--chip-tc-border)}
.chip.pc{background:var(--chip-pc);color:var(--chip-pc-text);border:1px solid var(--chip-pc-border)}
.chip.ic{background:var(--chip-ic);color:var(--chip-ic-text);border:1px solid var(--chip-ic-border)}
.chip.dt{background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;transition:transform 0.15s,border-color 0.15s,box-shadow 0.15s;cursor:pointer}
.card:hover{transform:translateY(-3px);border-color:var(--accent);box-shadow:var(--shadow)}
.card a{text-decoration:none;color:inherit;display:block}
.card .thumb{width:100%;aspect-ratio:16/9;background:var(--thumb-placeholder);overflow:hidden}
.card .thumb img{width:100%;height:100%;object-fit:cover;transition:transform 0.3s}
.card:hover .thumb img{transform:scale(1.05)}
.card .body{padding:14px}
.card .ttl{font-size:.9em;font-weight:600;margin-bottom:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.4}
.card .meta{font-size:.76em;color:var(--muted)}
.result-count{color:var(--muted);font-size:.84em;margin-bottom:12px}
.load-more{text-align:center;padding:20px}
.load-more button{padding:10px 28px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:.88em;font-family:inherit;cursor:pointer;transition:all 0.2s}
.load-more button:hover{border-color:var(--accent);color:var(--accent)}
.empty{text-align:center;padding:60px 20px;color:var(--muted)}
footer{text-align:center;padding:20px;color:var(--muted);border-top:1px solid var(--border);font-size:.8em}
.sidebar-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:150}
@media(max-width:900px){
  .sidebar{position:fixed;top:0;left:0;width:280px;height:100vh;z-index:200;transform:translateX(-100%);transition:transform 0.3s ease;padding:20px 16px}
  .sidebar.open{transform:translateX(0)}
  .sidebar-overlay.show{display:block}
  .layout{flex-direction:column}
  .main{padding:16px}
  header{padding:14px 16px}
  header h1{font-size:1.15em}
  .filter-btn{display:flex}
}
</style></head><body>
<header>
<h1>Palantir 博客归档</h1>
<div class="header-right">
<div class="toggle-group" id="langToggle">
<span data-lang="zh" class="active">中文</span>
<span class="sep">/</span>
<span data-lang="en">EN</span>
</div>
<button class="theme-btn" id="themeBtn" title="Theme">&#9728;</button>
</div>
</header>
<div class="sidebar-overlay" id="sidebarOverlay"></div>
<div class="layout">
<div class="sidebar" id="sidebar"></div>
<div class="main">
<div class="toolbar">
<button class="filter-btn" id="filterBtn">&#9776;</button>
<div class="search-wrap">
<span class="icon">&#128269;</span>
<input type="text" id="search" placeholder="搜索关键词...">
</div>
<select id="yearSelect"></select>
<select id="monthSelect"></select>
<select id="sortBy">
<option value="date-desc">最新优先</option>
<option value="date-asc">最早优先</option>
<option value="title-asc">标题 A-Z</option>
</select>
</div>
<div class="active-filters" id="af"></div>
<div class="result-count" id="rc"></div>
<div class="grid" id="grid"></div>
<div class="load-more" id="loadMore" style="display:none"><button id="loadMoreBtn">加载更多</button></div>
</div>
</div>
<footer>blog.palantir.com</footer>
<script>
var A=__A_DATA__;
var TC=__TC_DATA__;
var DT=__DT_DATA__;
var TAG_ZH=__TAG_ZH_DATA__;

var I18N={
  zh:{
    search_ph:"搜索关键词...",
    sort_new:"最新优先",sort_old:"最早优先",sort_az:"标题 A-Z",
    all_years:"所有年份",all_months:"所有月份",
    blog_cat:"博客分类",ind_tag:"行业标签",
    result_prefix:"共 ",result_suffix:" 篇文章",no_result:"未找到相关文章",
    filter:"筛选",load_more:"加载更多",
    months:["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
  },
  en:{
    search_ph:"Search keywords...",
    sort_new:"Newest first",sort_old:"Oldest first",sort_az:"Title A-Z",
    all_years:"All Years",all_months:"All Months",
    blog_cat:"Blog Categories",ind_tag:"Industry Tags",
    result_prefix:"Showing ",result_suffix:" articles",no_result:"No articles found",
    filter:"Filter",load_more:"Load More",
    months:["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  }
};

var lang="zh";
var F={bc:new Set(),tc:new Set(),pc:new Set(),ic:new Set()};
var dateFilter={year:null,month:null};
var accOpen={};
var subOpen={};
var pageSize=24;
var currentPage=0;

function t(key){return I18N[lang][key]}
function tt(tag){return lang==="zh"&&TAG_ZH[tag]?TAG_ZH[tag]:tag}

function applyLang(){
  document.getElementById("search").placeholder=t("search_ph");
  var sb=document.getElementById("sortBy");
  sb.options[0].text=t("sort_new");sb.options[1].text=t("sort_old");sb.options[2].text=t("sort_az");
  document.getElementById("filterBtn").innerHTML="&#9776; "+t("filter");
  document.getElementById("loadMoreBtn").textContent=t("load_more");
  document.querySelectorAll("#langToggle span[data-lang]").forEach(function(s){s.classList.toggle("active",s.dataset.lang===lang)});
  buildYearSelect();buildMonthSelect();buildSidebar();resetPage();render();
}

function applyTheme(theme){
  document.documentElement.setAttribute("data-theme",theme);
  document.getElementById("themeBtn").innerHTML=theme==="dark"?"&#9790;":"&#9728;";
}

function buildYearSelect(){
  var sel=document.getElementById("yearSelect");
  var h="<option value=''>"+t("all_years")+"</option>";
  var years=Object.keys(DT).sort(function(a,b){return b-a});
  for(var i=0;i<years.length;i++){
    var yr=years[i],yc=0;
    for(var mo in DT[yr]){yc+=DT[yr][mo]}
    var sel2=dateFilter.year===yr?" selected":"";
    h+="<option value='"+yr+"'"+sel2+">"+yr+" ("+yc+")</option>";
  }
  sel.innerHTML=h;
}

function buildMonthSelect(){
  var sel=document.getElementById("monthSelect");
  if(!dateFilter.year){sel.innerHTML="<option value=''>"+t("all_months")+"</option>";sel.disabled=true;return}
  sel.disabled=false;
  var h="<option value=''>"+t("all_months")+"</option>";
  var yr=dateFilter.year;
  var months=Object.keys(DT[yr]).sort(function(a,b){return a-b});
  for(var j=0;j<months.length;j++){
    var mo=months[j],sel2=dateFilter.month===mo?" selected":"";
    h+="<option value='"+mo+"'"+sel2+">"+t("months")[parseInt(mo,10)-1]+" ("+DT[yr][mo]+")</option>";
  }
  sel.innerHTML=h;
}

// Category hierarchy: tech subcategories under Engineering & Tech, product subcategories under Product
var CAT_TREE=[
  {key:"bc",name:"Engineering & Tech",subKey:"tc",subTags:[]},
  {key:"bc",name:"Product",subKey:"pc",subTags:[]},
  {key:"bc",name:"Privacy & Civil Liberties"},
  {key:"bc",name:"Palantir Global"},
  {key:"ic",name:null,labelKey:"ind_tag"}
];

function buildSidebar(){
  var sb=document.getElementById("sidebar");
  var h="";
  // Blog categories section
  var bcatKey="blogCategory";
  var bcatTotal=Object.keys(TC[bcatKey]).length;
  var isOpen=accOpen.bc!==false;
  h+="<div class='acc-section"+(isOpen?" open":"")+"' data-ck='bc'>";
  h+="<div class='acc-header' data-ck='bc'>";
  h+="<span class='acc-arrow'></span><span class='acc-title'>"+t("blog_cat")+"</span><span class='acc-count'>"+bcatTotal+"</span></div>";
  h+="<div class='acc-body'><div class='acc-tags'>";

  var btags=Object.keys(TC[bcatKey]).sort(function(a,b){return TC[bcatKey][b]-TC[bcatKey][a]});
  for(var k=0;k<btags.length;k++){
    var tg=btags[k],c=TC[bcatKey][tg];
    var tActive=F.bc.has(tg)?" active":"";
    h+="<div class='tag"+tActive+"' data-ck='bc' data-t='"+tg+"'><span>"+tt(tg)+"</span><span class='count'>"+c+"</span></div>";

    // Add sub-tags for Engineering & Tech and Product
    var subKey=null;
    if(tg==="Engineering & Tech")subKey="tc";
    else if(tg==="Product")subKey="pc";

    if(subKey){
      var subTags=Object.keys(TC[subKey]).sort(function(a,b){return TC[subKey][b]-TC[subKey][a]});
      var subOpenKey=tg;
      var subIsOpen=subOpen[subOpenKey];
      h+="<div class='sub-section"+(subIsOpen?" open":"")+"' data-sk='"+subKey+"' data-pg='"+tg+"'>";
      h+="<div class='sub-header' data-sk='"+subKey+"' data-pg='"+tg+"'><span class='sub-arrow'></span>"+(lang==="zh"?"子分类":"Subcategories")+"</div>";
      h+="<div class='sub-body'><div class='sub-tags'>";
      for(var j=0;j<subTags.length;j++){
        var stg=subTags[j],sc=TC[subKey][stg];
        var sActive=F[subKey].has(stg)?" active":"";
        h+="<div class='tag"+sActive+"' data-ck='"+subKey+"' data-t='"+stg+"'><span>"+tt(stg)+"</span><span class='count'>"+sc+"</span></div>";
      }
      h+="</div></div></div>";
    }
  }
  h+="</div></div></div>";

  // Industry tags section
  var icatKey="industry";
  var icatTotal=Object.keys(TC[icatKey]).length;
  var iIsOpen=accOpen.ic!==false;
  h+="<div class='acc-section"+(iIsOpen?" open":"")+"' data-ck='ic'>";
  h+="<div class='acc-header' data-ck='ic'>";
  h+="<span class='acc-arrow'></span><span class='acc-title'>"+t("ind_tag")+"</span><span class='acc-count'>"+icatTotal+"</span></div>";
  h+="<div class='acc-body'><div class='acc-tags'>";
  var itags=Object.keys(TC[icatKey]).sort(function(a,b){return TC[icatKey][b]-TC[icatKey][a]});
  for(var m=0;m<itags.length;m++){
    var itg=itags[m],ic=TC[icatKey][itg];
    var iActive=F.ic.has(itg)?" active":"";
    h+="<div class='tag"+iActive+"' data-ck='ic' data-t='"+itg+"'><span>"+tt(itg)+"</span><span class='count'>"+ic+"</span></div>";
  }
  h+="</div></div></div>";

  sb.innerHTML=h;

  // Bind events
  sb.querySelectorAll(".acc-header").forEach(function(el){
    el.addEventListener("click",function(){
      var ck=el.dataset.ck;
      accOpen[ck]=!accOpen[ck];
      el.parentElement.classList.toggle("open");
    });
  });
  sb.querySelectorAll(".sub-header").forEach(function(el){
    el.addEventListener("click",function(e){
      e.stopPropagation();
      var pg=el.dataset.pg;
      subOpen[pg]=!subOpen[pg];
      el.parentElement.classList.toggle("open");
    });
  });
  sb.querySelectorAll(".tag").forEach(function(el){
    el.addEventListener("click",function(e){
      e.stopPropagation();
      var ck=el.dataset.ck,tg=el.dataset.t;
      if(F[ck].has(tg)){F[ck].delete(tg)}else{F[ck].add(tg)}
      el.classList.toggle("active");
      resetPage();render();
    });
  });
}

function getFiltered(){
  var q=document.getElementById("search").value.toLowerCase().trim();
  return A.filter(function(a){
    if(!q)return true;
    var title=lang==="zh"?(a.tt||a.t||""):(a.t||"");
    if(title.toLowerCase().indexOf(q)>=0)return true;
    if((a.ds||"").toLowerCase().indexOf(q)>=0)return true;
    if((a.sn||"").toLowerCase().indexOf(q)>=0)return true;
    return false;
  }).filter(function(a){
    if(dateFilter.year){
      var y=(a.d||"").substring(0,4);
      if(y!==dateFilter.year)return false;
      if(dateFilter.month){
        var m=(a.d||"").substring(5,7);
        if(m!==dateFilter.month)return false;
      }
    }
    for(var ck in F){
      if(F[ck].size>0){
        var arr=a[ck]||[];
        var has=false;
        F[ck].forEach(function(tg){if(arr.indexOf(tg)>=0)has=true});
        if(!has)return false;
      }
    }
    return true;
  });
}

function resetPage(){currentPage=0}

function formatDate(d){
  if(!d)return"";
  if(d.length>=10){
    var y=d.substring(0,4),mo=parseInt(d.substring(5,7),10)-1,day=d.substring(8,10);
    if(lang==="zh")return y+"年"+t("months")[mo]+day+"日";
    return t("months")[mo]+" "+day+", "+y;
  }
  if(d.length>=7){
    var y2=d.substring(0,4),mo2=parseInt(d.substring(5,7),10)-1;
    return t("months")[mo2]+" "+y2;
  }
  return d;
}

function render(){
  var f=getFiltered();
  var sb=document.getElementById("sortBy").value;
  if(sb==="date-desc")f.sort(function(a,b){return (b.d||"").localeCompare(a.d||"")});
  else if(sb==="date-asc")f.sort(function(a,b){return (a.d||"").localeCompare(b.d||"")});
  else if(sb==="title-asc"){
    f.sort(function(a,b){
      var ta=lang==="zh"?(a.tt||a.t):(a.t||"");
      var tb=lang==="zh"?(b.tt||b.t):(b.t||"");
      return ta.localeCompare(tb);
    });
  }

  document.getElementById("rc").textContent=t("result_prefix")+f.length+" / "+A.length+t("result_suffix");

  // Active filter chips
  var afh="";
  var CC={bc:"bc",tc:"tc",pc:"pc",ic:"ic"};
  for(var ck in F){
    F[ck].forEach(function(tg){
      afh+="<span class='chip "+CC[ck]+"' data-ck='"+ck+"' data-t='"+tg+"'>"+tt(tg)+" &times;</span>";
    });
  }
  if(dateFilter.year){
    var dl=dateFilter.year;
    if(dateFilter.month)dl=dateFilter.year+" "+t("months")[parseInt(dateFilter.month,10)-1];
    afh+="<span class='chip dt' id='dateChip'>"+dl+" &times;</span>";
  }
  document.getElementById("af").innerHTML=afh;
  document.querySelectorAll("#af .chip").forEach(function(el){
    el.addEventListener("click",function(){
      var ck=el.dataset.ck,tg=el.dataset.t;
      if(ck&&tg){F[ck].delete(tg);buildSidebar();resetPage();render();}
      else if(el.id==="dateChip"){dateFilter.year=null;dateFilter.month=null;buildYearSelect();buildMonthSelect();resetPage();render();}
    });
  });

  // Pagination
  var visible=f.slice(0,(currentPage+1)*pageSize);
  var g=document.getElementById("grid");
  if(visible.length===0){g.innerHTML="<div class='empty'>"+t("no_result")+"</div>";document.getElementById("loadMore").style.display="none";return}

  var gh="";
  for(var i=0;i<visible.length;i++){
    var a=visible[i];
    var title=lang==="zh"?(a.tt||a.t||""):(a.t||"");
    var th=a.th?"<div class='thumb'><img src='"+a.th+"' loading='lazy'></div>":"<div class='thumb'></div>";
    gh+="<div class='card'><a href='"+a.hp+"' target='_blank'>"+th+
      "<div class='body'><div class='ttl'>"+esc(title)+"</div>"+
      "<div class='meta'>"+formatDate(a.d)+"</div></div></a></div>";
  }
  g.innerHTML=gh;

  // Show/hide load more
  var lm=document.getElementById("loadMore");
  if(f.length>visible.length){lm.style.display="block"}else{lm.style.display="none"}
}

function esc(s){return(s||"").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

// Events
document.getElementById("themeBtn").addEventListener("click",function(){
  var cur=document.documentElement.getAttribute("data-theme");
  applyTheme(cur==="dark"?"light":"dark");
});
document.querySelectorAll("#langToggle span[data-lang]").forEach(function(el){
  el.addEventListener("click",function(){
    lang=el.dataset.lang;
    applyLang();
  });
});
document.getElementById("search").addEventListener("input",function(){resetPage();render()});
document.getElementById("sortBy").addEventListener("change",function(){resetPage();render()});
document.getElementById("yearSelect").addEventListener("change",function(){
  dateFilter.year=this.value||null;dateFilter.month=null;buildMonthSelect();resetPage();render();
});
document.getElementById("monthSelect").addEventListener("change",function(){
  dateFilter.month=this.value||null;resetPage();render();
});
document.getElementById("loadMoreBtn").addEventListener("click",function(){
  currentPage++;render();
});
document.getElementById("filterBtn").addEventListener("click",function(){
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sidebarOverlay").classList.add("show");
});
document.getElementById("sidebarOverlay").addEventListener("click",function(){
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebarOverlay").classList.remove("show");
});

// Init
applyTheme("light");
applyLang();
</script></body></html>
"""

html = HTML.replace('__A_DATA__', A_JSON)
html = html.replace('__TC_DATA__', TC_JSON)
html = html.replace('__DT_DATA__', DT_JSON)
html = html.replace('__TAG_ZH_DATA__', TAG_ZH_JSON)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Done! index.html rebuilt with {len(A)} articles")
