# 03-syncledger（双核对账）

Syncledger — 跨库/跨系统对齐对账：双端抽取 → 对齐键对账 → 差异处置 → 批次互证。

与 Feedstitch（多源 Feed 归并）、Batchgate（作业依赖编排）主链路不同。夹具全本地，不连活库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5300 |
| API | http://localhost:10300 |

## 主链

配置对账对与对齐键 → 触发双端抽取并对齐 → 落差异行与批次计数 → 页面互证

## 种子对账对

- **inventory_hq_vs_store**：总部库存 ↔ 门店库存（`sku_id`+`store_id`，比对 `qty`）
- **payment_vs_ledger**：支付网关 ↔ 账务流水（`txn_id`，比对 `amount`/`currency`）
- **sku_catalog_a_vs_b**：目录 A ↔ 目录 B（`sku_code`，比对 `name`/`category`）

底座默认只**记差异、不自动盖写**；差异处置/契约/审计页留表与入口，深逻辑留给后题。侧栏不叫「工单」，避免撞禁名单「工单客服」。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 已知差异抑制（本切口）

同一对反复对账时，已确认暂不处理的差异会被按指纹登记，后续对账不再进待处置。

- **指纹**：差异类型 + 对齐键 + 左右两侧参与比对字段值的 SHA-256 摘要（`compare_fields` 之外
  的列如 `updated_at` 不参与）。指纹来自 `backend/app/engines/fingerprint.py`。
- **不改批次统计**：被抑制的差异行照常落库、照常进 `diff_total`，同时计入批次
  `suppressed_count`；`suppressed_count + 待处置数 = diff_total`，审计页逐项核对。
- **指纹变化即失效**：任一侧比对字段值变化 → 下一趟对账指纹不匹配 → 原抑制置
  `invalidated`，差异标 `reactivated` 并重新计入 `reactivated_count`、回到待处置。
- **处置单冲突策略（每对互斥二选一）**：
  - `reject`（默认）：对应差异仍有未关处置单时拒绝登记（事件留痕 `register_rejected_ticket_conflict`）。
  - `allow_and_suspend`：登记成功，未关处置单自动置 `suspended_by_suppression`；撤销或抑制失效时恢复 `open`。
- **对账进行中禁改**：批次处于 `extracting` / `aligning` 时，登记与撤销（以及策略切换）返回
  `409 run_in_progress`，避免本趟统计中途被改。

### 演示（页面）

1. 「对账台」跑一趟 → 「已知差异抑制」按差异行登记抑制。
2. 再跑一趟：该行显示「已抑制」，批次「抑制数」+1，待处置减少，差异行仍在清单里。
3. 「改右端/左端值」写运行时夹具 → 再跑一趟：该行变「重新激活」，抑制登记变「已失效」。
4. 「开处置单」后按当前策略登记：`reject` 报冲突，`allow_and_suspend` 挂起处置单。
5. 「对账台」把「抽取/对齐停留毫秒」设为几千 → 运行期间抑制页按钮全部禁用并给出原因。

运行时夹具复制到 `DATA_DIR/fixtures`，镜像内 `app/fixtures` 作为基线冻结在 `DATA_DIR/fixtures_baseline`；
「还原源夹具」可一键回滚。

### 测试

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt httpx
.venv/bin/python -m pytest
```

## 0-1 切口（未实现，见出题规划）

`master_slave_pick` / `side_only_policy` / `window_buffer` / `diff_disposition_flow` / `batch_idempotency` / …
