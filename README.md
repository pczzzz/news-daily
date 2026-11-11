# 每日资讯日报

每天早上 7:30，自动从 48 个一手信源抓取政治、财经、科技、科学、体育等 14 个板块的新闻，按重要性打分排序，再把**原文正文完整抓下来逐段直译成中文**，生成一份不用翻墙、不用懂英文也能直接读的日报。

**为什么不用现成的 RSS 阅读器？** 因为你的网络直连不了 Inoreader、Feedly、BBC、路透——实测全部超时。而 GitHub 是通的。所以这里把抓取任务放到 **GitHub 的服务器**上跑（它们在海外，能正常访问这些源），你只需要看结果。

---

## 一、5 分钟上手

### 第 1 步：建仓库

1. 登录 [github.com](https://github.com)（没有账号就注册一个，免费）
2. 右上角 `+` → **New repository**
3. 仓库名填 `news-daily`，选 **Public**（公开仓库的 Actions 完全免费），**不要**勾选任何初始化文件
4. 点 **Create repository**

### 第 2 步：上传文件

在新建的仓库页面，点 **uploading an existing file**，把这个 `资讯日报` 文件夹里的**全部内容**拖进去：

```
.github/workflows/daily.yml   ← 定时任务配置
config/sources.yml            ← 订阅源清单
scripts/fetch_news.py         ← 抓取脚本
requirements.txt
README.md
```

> 注意：`.github` 是隐藏文件夹，在资源管理器里要先开启「显示隐藏项目」才能看到。如果拖拽失败，用 Git 命令行推上去更稳。

点 **Commit changes**。

### 第 3 步：开启写权限

仓库 → **Settings** → 左侧 **Actions** → **General** → 拉到最下面 **Workflow permissions** → 选 **Read and write permissions** → **Save**。

> 这一步不能漏，否则 Actions 跑完没法把日报写回仓库。

### 第 4 步：手动跑一次

仓库 → **Actions** 标签 → 左侧 **每日资讯日报** → 右侧 **Run workflow** → 绿色按钮。

约 1～2 分钟后刷新，能看到一次绿色成功记录，仓库里会多出 `docs/` 目录。

### 第 5 步：看日报

仓库已经开启 GitHub Pages，直接访问：

```
https://pczzzz.github.io/news-daily/
```

这个域名国内可直连，**存成浏览器书签，每天早上点一下就行。**

> 备选地址（如果 Pages 被抽风）：
> - 原站：`https://raw.githubusercontent.com/pczzzz/news-daily/main/docs/index.html`（浏览器会当纯文本，右键“另存为 .html”再打开）
> - statically.io CDN：`https://cdn.statically.io/gh/pczzzz/news-daily/main/docs/index.html`（公司网络实测超时，仅作外网备份）

---

## 二、日报长什么样

```
# 每日资讯日报 · 2026-11-10

> 生成时间：2026-11-10 07:31　共 28 条 · 来自 14/16 个源 · 中文为逐段直译

## 国际硬新闻
**1. 库什纳与威特科夫重启和谈，力图结束俄乌战争**
　　`NPR World` · 11-10 09:38 · 评分 80 · [原文](...)
　　Kushner and Witkoff renew peace talks to end war between Russia and Ukraine
　　特朗普特使在阿布扎比与俄乌谈判代表重启和谈。
　　▸ 展开全文（中文翻译）

## 科技新闻
**2. 纽约州 AI 安全法生效，OpenAI、Anthropic 面临新监管**
　　`TechCrunch` · 11-10 20:52 · 评分 50 · [原文](...)
　　▸ 展开全文（中文翻译）
```

每条都可以：
- 直接读**中文标题 + 摘要**
- 点「展开全文」看**整篇正文的中文直译**（逐段对应，不概括、不删减）
- 展开后的底部还能切到 **English original** 对照英文原文
- 右侧「阅读原文 →」直达源站（海外站可能打不开，但正文已经抓回来了）

排序规则：

| 因素 | 加分 |
|---|---|
| 命中「战争/导弹/政变/停火/制裁/大选」等关键词 | +40 |
| 命中「外交/谈判/议会/国防/条约」等 | +20 |
| 24 小时内发布 | +10 |
| 源权重（10 分制）× 1.5 | 最多 +15 |
| 命中「震惊/速看/广告」等标题党词 | −25 |

低于 35 分的直接丢弃。超过 7 天的旧闻丢弃。

---

## 三、想改什么

### 改推送时间

编辑 `.github/workflows/daily.yml` 第 6 行：

```yaml
- cron: "30 23 * * *"
```

cron 用 **UTC 时间**，北京时间要减 8 小时。所以：

| 想要北京时间 | 写成 |
|---|---|
| 07:30 | `30 23 * * *` |
| 08:00 | `0 0 * * *` |
| 12:00 | `0 4 * * *` |
| 每天两次（早 8 晚 8） | 写两行 cron |

### 加/减信源

编辑 `config/sources.yml`，在对应分类下加一条：

```yaml
  - name: "显示名称"
    url: "https://example.com/feed.xml"
    category: "国际硬新闻"    # 或 深度政论 / 中文视角 / 军事防务
    weight: 8                 # 1-10，越高排越前
    lang: en
```

**只要是标准 RSS 地址就能加**，不用改代码。改完下次运行自动生效。

### 打开军事防务板块

`config/sources.yml` 最下面有注释掉的 Defense News 和 The War Zone，去掉 `#` 即可。

### 调整筛选松紧

`config/sources.yml` 顶部的 `settings`：

```yaml
min_score: 35         # 调低 → 收录更多（但更杂）；调高 → 更精
max_per_source: 6     # 每个源最多取几条
max_items: 40         # 日报总条数上限
max_per_category: 12  # 单个板块最多几条（防止科技板块把国际新闻挤没）
max_age_days: 7       # 超过几天的旧闻丢掉

# 原文正文 + 中文翻译
enrich_article: true      # 抓原文正文（失败自动降级为 RSS 摘要）
article_paragraphs: 10    # 每篇最多保留几段（10 段约 1500-2500 字）
translate: true           # 逐段直译成中文
translate_concurrency: 6  # 翻译并发数（太大容易被限流）
```

---

## 四、常见问题

**Q：Actions 显示成功，但打开页面是 404？**
CDN 有缓存延迟，等 2～3 分钟。如果还不行，检查仓库里有没有 `docs/index.html` 这个文件。

**Q：日报是空的？**
说明所有源都抓取失败了。点开 Actions 的日志看「本次抓取失败的源」那一节，里面写了每个源的具体错误。最常见的是网络超时——GitHub 服务器偶尔也会抽风，重跑一次就好。

**Q：为什么有些源一直失败？**
有些网站（如 AP News）会拦截爬虫返回 403，这是对方策略，改 `User-Agent` 也未必有效。如果某个源长期失败，直接从 `sources.yml` 里删掉，别浪费时间。

**Q：想让日报推送到微信/邮箱？**
可以在 `daily.yml` 最后加一步调用 webhook。目前版本没做，因为国内推送渠道（企微/飞书/钉钉）都需要你提供机器人地址。需要的话告诉我。

**Q：翻译质量怎么样？为什么不直接总结？**
用的是 Google 翻译接口做**逐段直译**，只翻译、不改写、不概括、不删减——你要的是一手信息，总结一遍就变成二次加工了。如果某段翻译失败，那段会直接显示英文原文并标注，不会静默丢掉。

**Q：能加 AI 摘要吗？**
能。你的公司网关 `aigateway.tongwei.com` 解析到阿里云公网 IP，GitHub Actions 理论上能访问。在脚本里加一个 `requests.post` 调 `/v1/chat/completions` 即可，成本约几毛钱一天。目前故意没加，因为**每多一个外部依赖就多一个故障点**，先跑稳再说。

**Q：数据会不会泄露？**
所有处理都在你自己的 GitHub 私有环境里跑，不经过任何第三方服务。日报文件存在你自己的仓库中。

---

## 五、目录结构

```
资讯日报/
├── .github/workflows/daily.yml   # 定时任务
├── config/sources.yml            # 信源清单（改这里）
├── scripts/fetch_news.py         # 抓取 + 打分 + 渲染
├── requirements.txt
├── docs/
│   ├── index.html                # 最新日报（网页版）
│   ├── daily/2026-11-10.md       # 按日期归档
│   ├── history.json              # 跨日去重索引
│   └── archive.json              # 历史日期列表
└── README.md
```

## 六、当前信源

共 **48 个源、14 个板块**，按以下顺序展示：

| 板块 | 信源 |
|---|---|
| 国际硬新闻 | BBC World、Al Jazeera、The Guardian、NPR、WSJ、France 24、DW |
| 深度政论 | Foreign Affairs、Foreign Policy、The Diplomat、War on the Rocks |
| 中国与亚太 | SCMP、日经中文网、Japan Times |
| 财经宏观 | CNBC、MarketWatch、华尔街见闻 |
| 商业与公司 | WSJ Business、Business Insider、Fortune |
| 科技新闻 | Ars Technica、MIT Technology Review、The Verge、TechCrunch、Hacker News、IT之家、爱范儿、少数派 |
| 外媒报道的中国 | The Guardian · China、BBC · China、The Economist · China、Sixth Tone、中国数字时代 |
| 健康医疗 | STAT News、Nature |
| 社会民生 | The Guardian Society、澎湃新闻 |
| 汽车出行 | Electrek、InsideEVs |
| 体育 | ESPN、BBC Sport |
| 文化娱乐 | Variety、Polygon |
| 教育 | Inside Higher Ed |
| 中文视角 | 界面新闻、BBC 中文、纽约时报中文网、端传媒 |

> **板块专属关键词**：每个板块在 `keywords.category_boost` 下有一组关键词（命中 +20），只对该板块的条目生效。这样同一条「AI 芯片」新闻不会同时把国际新闻和科技新闻的分数一起抬上去。

> **侧边导航**：桌面端左侧固定板块列表，每项右侧显示该板块当天条数，滚动时自动高亮当前板块；移动端收成右下角悬浮的「☰ 板块导航」抽屉。点击板块名直接跳到对应位置（`<h2 id="板块名">` 锚点）。
