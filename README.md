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
| `dist/dashboard.html` | 自包含看板，数据内联，双击即可打开，离线可用 |

## 命令

```bash
python main.py          # 抓取 + 重建看板（默认）
python main.py fetch    # 只抓取，并追加一条对账记录
python main.py build    # 用已有 snapshot 重建 HTML
```

## 配置（全部走环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `STONK_MINT` | `6GmAFSYs…UNgx` | 目标 mint |
| `STONK_RPC_URL` | `https://api.mainnet-beta.solana.com` | **跑定时任务务必换成 Helius / QuickNode**，公共 RPC 限速很紧 |
| `STONK_INITIAL_SUPPLY` | `1000000000` | 初始供应假设，看板会显式标注并反推校验 |
| `STONK_API_BASE` | `https://www.stonkfun.xyz/api/public/v1` | API 根路径 |

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
stonk/collect.py     抓取、对账、派生指标
stonk/render.py      snapshot + 模板 → 自包含 HTML
stonk/template.html  看板模板（body-only，数据从 /*__SNAPSHOT__*/ 注入）
```

`template.html` 刻意写成 body-only，因此同一份模板既能包成本地 HTML（`render(standalone=True)`，自动补 `<head>` 和 charset），也能直接发布成 Artifact。
