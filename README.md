# STONK 销毁看板

把 stonkfun.xyz 公开 API 和 Solana 链上供应量拉到一起，生成一个自包含的静态销毁看板。

核心不是"平台说烧了多少"，而是**两个独立计数的差额**：链上 `1e9 − getTokenSupply` 与平台销毁台账 `/tokens/{mint}/burns` 的差多少、往哪边差。每次抓取都会往 `data/recon_history.jsonl` 追加一行，差额随时间的走向能区分两种情况：

- 围绕 0 抖动 → 取数时点错位（API 有 30s 缓存，RPC slot 可能更早）
- 稳定单向偏移 → 台账缺记、平台流程之外的销毁，或初始供应假设不等于 1e9

## 快速开始

```bash
# Windows
setup.bat
activate.bat
python main.py

# macOS / Linux
./setup.sh
source activate.sh
python main.py
```

产物：

| 路径 | 内容 |
|---|---|
| `data/snapshot.json` | 一次抓取的全部原始 + 派生数据 |
| `data/recon_history.jsonl` | 每次抓取一行的对账记录（差额时间序列） |
| `dist/index.html` | 自包含看板，数据内联，双击即可打开，离线可用 |

## 部署到 Vercel

`dist/` 就是部署根目录，里面已经放好 `vercel.json` 和 `api/supply.js`。

```bash
vercel login          # 只需一次
./deploy.sh           # 或 Windows 下 deploy.bat：拉最新数据 → 重建 → 部署
```

部署后页面右上角的**更新数据**按钮会让浏览器直接调 stonkfun API 和链上 RPC 重算全部指标，不需要服务端定时任务，Hobby 套餐免费即可。分时台账存在浏览器 localStorage 里，按签名去重，刷新页面不丢。

**为什么需要 `api/supply.js`**：公共 Solana RPC 对带 `Origin` 头的请求一律返回 403，页面没法直连。这个函数在服务端代理一次 `getTokenSupply`——方法和 mint 都写死，不会变成别人的免费公共 RPC。想换成 Helius / QuickNode，在 Vercel 项目里配环境变量即可，页面不用动：

```
STONK_RPC_URL = https://mainnet.helius-rpc.com/?api-key=xxx
```

本地直接双击打开 `dist/index.html` 时没有这个函数，会自动回退到浏览器可用的公共节点（用 `text/plain` 规避 CORS 预检）。

## 命令

```bash
python main.py                        # 抓取 + 重建看板（默认）
python main.py fetch                  # 只抓取，并追加一条对账记录
python main.py build                  # 用已有 snapshot 重建 HTML
python main.py watch --interval 180   # 按间隔持续抓取，累积分时数据
```

## 分时看板与本地台账

`/burns` 和 `/revenue` 的明细都是单页 100 条，**无法回补历史**——想看分时就只能自己攒。每次抓取会把两个流按签名去重合并进本地台账：

| 文件 | 内容 |
|---|---|
| `data/burns.jsonl` | 逐笔销毁（时间 / 枚数 / USD / 来源） |
| `data/buybacks.jsonl` | 逐笔回购（买入枚数 / 成交额 / 报价币） |
| `data/coverage.json` | **实际采集到的时间区间**，按流分别记录 |

看板里分时区块可切 1/5/15/60 分钟分箱与 1/6/24 小时窗口，两条曲线：

- **每箱销毁枚数** —— 枚数口径。日线端点只给美元，枚数只能靠本地累积
- **回购成交均价** —— `boughtValueUsd ÷ boughtTokens`，国库实际买入 STONK 的价格

`coverage.json` 是这套东西的诚实性保证：**没采集到的区间会画成"未采集"空档，而不是画成 0**。两者含义完全不同，混在一起等于编数据。每个 tile 也各自标注所属流的采集覆盖率，因为两个流的覆盖可能差很远。

**轮询间隔怎么定**：100 条在平时约等于 25 分钟，但爆量时可能只有几分钟。默认 180 秒留了余量。如果某次返回的 100 条全是没见过的记录（且台账原本非空），说明轮询已经落后、有记录在没看到之前就被挤出去了——这时 `fetch` 会往 stderr 打 `WARNING polling fell behind`，看板上对应区间也会显示成空档。

## 配置（全部走环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `STONK_MINT` | `6GmAFSYs…UNgx` | 目标 mint |
| `STONK_RPC_URL` | `https://api.mainnet-beta.solana.com` | **跑定时任务务必换成 Helius / QuickNode**，公共 RPC 限速很紧 |
| `STONK_INITIAL_SUPPLY` | `1000000000` | 初始供应假设，看板会显式标注并反推校验 |
| `STONK_API_BASE` | `https://www.stonkfun.xyz/api/public/v1` | API 根路径 |
| `STONK_WATCH_INTERVAL` | `180` | `watch` 轮询间隔（秒） |
| `STONK_INTRADAY_HOURS` | `48` | 嵌入页面的分时窗口长度 |

## 数据口径

字段名一律以 `/openapi.json` 为准。

- **链上供应**：Solana JSON-RPC `getTokenSupply`，供应量只信这一侧。响应里的 slot 会一并记录，方便事后复查。
- **销毁台账**：`/tokens/{mint}/burns`。`totals` 是全量累计；`burns` 明细列表单次上限 100 条。
- **日线收入**：`/revenue/history`，按 UTC 日 keyed，一次拉全无日期参数。`dailyRevenue` 是入库手续费，`dailyHoldersRevenue` 是拿去回购销毁的部分，`dailyProtocolRevenue` 是留存。创作者与 reward 持仓的手续费直接从 Raydium 领取，**不计入**这里。
- **coverage**：报告有多少 ledger 行因为没有 USD 报价被当 0 计。看板单独一块展示——它直接决定上面的美元数被低估多少。
- **⚠️ 平台 vs 单币**：`/revenue` 和 `/stats` 里的 burns 统计覆盖平台全部 mint（当前 325 个），**不是 STONK 单币口径**，两者不可混用。看板里这部分单独成块并标注清楚。

## 限速

API 300 次/分钟 per IP，响应带 `X-RateLimit-Remaining`，429 时带 `Retry-After`。客户端已按 `Retry-After` 退避重试；一次完整抓取消耗 5 次调用。

## 结构

```
main.py              CLI 入口
stonk/config.py      配置（环境变量覆盖）
stonk/api.py         StonkFun API 客户端 + Solana RPC
stonk/ledger.py      分时台账：去重合并、采集区间记录
stonk/collect.py     抓取、对账、派生指标
stonk/render.py      snapshot + 模板 → 自包含 HTML
stonk/template.html  看板模板（body-only，数据从 /*__SNAPSHOT__*/ 注入）
```

`template.html` 刻意写成 body-only，因此同一份模板既能包成本地 HTML（`render(standalone=True)`，自动补 `<head>` 和 charset），也能直接发布成 Artifact。
