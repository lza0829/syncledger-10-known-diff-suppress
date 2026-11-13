<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON, postJSON } from '../api'

const route = useRoute()
const pairs = ref([])
const pairId = ref(null)
const data = ref(null)
const err = ref('')
const notice = ref('')
const busy = ref(false)
const conflict = ref(null)
const changeTarget = ref(null)
const changeField = ref('')
const changeValue = ref('')

const stateLabel = { pending: '待处置', suppressed: '已抑制', reactivated: '重新激活' }
const stateClass = { pending: 'warn', suppressed: 'ok', reactivated: 'danger' }
const kindLabel = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }
const kindClass = { left_only: 'warn', right_only: 'warn', field_mismatch: 'danger' }
const statusLabel = {
  active: '生效中',
  invalidated: '已失效（指纹变化）',
  revoked: '已撤销',
}

const locked = computed(() => !!data.value && data.value.mutations_allowed === false)
const policy = computed(() => data.value?.policy || 'reject')

async function load() {
  err.value = ''
  data.value = await getJSON(`/api/suppressions?pair_id=${pairId.value}`)
}

async function bootstrap() {
  pairs.value = await getJSON('/api/pairs')
  const q = Number(route.query.pair_id)
  pairId.value = q || pairs.value[0]?.id || null
  if (pairId.value) await load()
}

function quietNotice(msg) {
  notice.value = msg
  setTimeout(() => { if (notice.value === msg) notice.value = '' }, 4000)
}

async function act(fn, successMsg) {
  err.value = ''
  conflict.value = null
  busy.value = true
  try {
    const res = await fn()
    await load()
    if (successMsg) quietNotice(typeof successMsg === 'function' ? successMsg(res) : successMsg)
    return res
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function enableSuppression(diff) {
  await act(
    () => postJSON('/api/suppressions', { diff_id: diff.id }),
    (res) => res.suspended_ticket_ids.length
      ? `已登记抑制；未关处置单 #${res.suspended_ticket_ids.join('、#')} 已自动挂起`
      : '已登记抑制；下一趟对账将按指纹匹配',
  )
}

async function revoke(item) {
  await act(
    () => postJSON(`/api/suppressions/${item.id}/revoke`, {}),
    (res) => res.restored_ticket_ids.length
      ? `已撤销抑制；处置单 #${res.restored_ticket_ids.join('、#')} 已恢复为未关`
      : '已撤销抑制',
  )
}

async function setPolicy(value) {
  await act(
    () => postJSON('/api/suppressions/policy', { pair_id: pairId.value, policy: value }),
    () => `处置单策略已切换为「${value === 'reject' ? '拒绝抑制' : '允许抑制并挂起处置单'}」`,
  )
}

async function openTicket(diff) {
  await act(
    () => postJSON('/api/dispositions', { diff_id: diff.id }),
    '已在差异处置页开出处置单（open）；此时再登记抑制会触发策略冲突',
  )
}

async function openConflict(diff) {
  err.value = ''
  conflict.value = null
  busy.value = true
  try {
    await postJSON('/api/suppressions', { diff_id: diff.id })
    await load()
    quietNotice('已登记抑制')
  } catch (e) {
    conflict.value = { diff, message: String(e.message || e) }
    await load()
  } finally {
    busy.value = false
  }
}

function pickSourceRow(diff, side) {
  const row = side === 'left' ? diff.left : diff.right
  if (!row) {
    err.value = '该差异在选定侧没有行（仅对侧有），无法在此侧改值'
    return
  }
  changeTarget.value = { diff, side, row }
  const fields = data.value?.pair?.compare_fields || []
  changeField.value = fields[0] || Object.keys(row).find((k) => k !== 'sku_id') || ''
  changeValue.value = row[changeField.value]
}

async function submitSourceChange() {
  const t = changeTarget.value
  if (!t) return
  const changes = { [changeField.value]: coerce(changeValue.value) }
  const res = await act(
    () => postJSON('/api/demo/source-change', {
      pair_id: pairId.value,
      side: t.side,
      align_key: t.diff.align_key,
      changes,
    }),
    (r) => `已将${t.side === 'left' ? '左' : '右'}端 ${JSON.stringify(r.align_key)} 的 ${r.changed_fields.join(', ')} 由 ${JSON.stringify(r.before[changeField.value] ?? null)} 改为 ${JSON.stringify(r.after[changeField.value] ?? null)}；再跑一趟对账以观察抑制是否失效`,
  )
  if (res) changeTarget.value = null
}

async function resetSource() {
  await act(
    () => postJSON('/api/demo/source-reset', { pair_id: pairId.value }),
    '已把本对的运行时夹具还原为基线',
  )
}

function coerce(v) {
  if (v === '') return null
  const n = Number(v)
  if (!Number.isNaN(n) && String(n) === String(v).trim()) return n
  return v
}

const NON_COMPARED = new Set(['updated_at', 'paid_at', 'booked_at'])

function pickValues(row) {
  if (!row) return null
  const fields = data.value?.pair?.compare_fields
  if (fields?.length) {
    return Object.fromEntries(fields.map((f) => [f, row[f]]))
  }
  return Object.fromEntries(Object.entries(row).filter(([k]) => !NON_COMPARED.has(k)))
}

watch(pairId, async () => {
  changeTarget.value = null
  try { await load() } catch (e) { err.value = String(e.message || e) }
})

onMounted(async () => {
  try { await bootstrap() } catch (e) { err.value = String(e.message || e) }
})
</script>

<template>
  <div class="page">
    <h1>已知差异抑制</h1>
    <p class="muted">
      按差异指纹登记已知差异：指纹 = 差异类型 + 对齐键 + 左右两侧参与比对字段值的摘要。
      源两侧相关行指纹未变前，本趟记为「已抑制」、不进待处置，但仍计入批次「抑制数」；
      任一侧字段值变化则指纹变化，抑制自动失效并重新待处置。抑制不删除历史差异行。
    </p>

    <div class="panel">
      <label>
        对账对
        <select v-model.number="pairId" style="display:block;margin-top:0.35rem;min-width:20rem">
          <option v-for="p in pairs" :key="p.id" :value="p.id">
            {{ p.title }}（{{ p.code }}）
          </option>
        </select>
      </label>
      <p v-if="data" style="margin:0.6rem 0 0">
        当前未关处置单
        <span class="tag" :class="data.open_ticket_conflicts.length ? 'warn' : ''">
          {{ data.open_ticket_conflicts.length }}
        </span>
        <span class="muted" style="margin-left:0.5rem">
          {{ data.open_ticket_conflicts.length
            ? (policy === 'reject'
              ? '策略为拒绝抑制：对这些差异登记会被拒绝'
              : '策略为允许抑制：登记时这些处置单将自动挂起')
            : '无冲突风险' }}
        </span>
      </p>
      <ul v-if="data.open_ticket_conflicts.length" class="mono" style="margin:0.35rem 0 0;padding-left:1.1rem">
        <li v-for="t in data.open_ticket_conflicts" :key="t.ticket_id">
          #{{ t.ticket_id }} · {{ t.diff_kind }} · {{ JSON.stringify(t.align_key) }} · {{ t.status }}
        </li>
      </ul>
      <p v-if="data" style="margin:0.6rem 0 0">
        处置单策略：
        <span class="tag" :class="policy === 'reject' ? 'warn' : 'ok'">{{ data.policy_label }}</span>
        <span class="muted" style="margin-left:0.6rem">两种策略互斥，按当前选择贯彻</span>
      </p>
      <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
        <button class="secondary" :disabled="busy || locked || policy === 'reject'" @click="setPolicy('reject')">
          选项 A：拒绝抑制
        </button>
        <button class="secondary" :disabled="busy || locked || policy === 'allow_and_suspend'" @click="setPolicy('allow_and_suspend')">
          选项 B：允许抑制并挂起处置单
        </button>
        <button class="secondary" :disabled="busy || locked" @click="resetSource">还原源夹具</button>
      </div>
    </div>

    <p v-if="locked && data.running.length" class="panel tag warn" style="display:block">
      对账批次 {{ data.running[0].batch_no }} 正处于 {{ data.running[0].status }} 阶段：抑制登记、撤销与策略修改均已禁止，避免本趟统计中途被改。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="notice" class="tag ok">{{ notice }}</p>

    <div class="panel" v-if="data && data.latest_batch && data.latest_counts">
      <h3 style="margin-top:0">
        最近批次 <span class="mono">{{ data.latest_batch.batch_no }}</span>
      </h3>
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ data.latest_counts.diff_total }}</div><div class="stat-label">差异合计</div></div>
        <div class="stat"><div class="stat-num">{{ data.latest_counts.suppressed }}</div><div class="stat-label">抑制数</div></div>
        <div class="stat"><div class="stat-num">{{ data.latest_counts.reactivated }}</div><div class="stat-label">重新激活</div></div>
        <div class="stat"><div class="stat-num">{{ data.latest_counts.pending }}</div><div class="stat-label">待处置</div></div>
        <div class="stat"><div class="stat-num">{{ data.active_count }}</div><div class="stat-label">生效中抑制条数</div></div>
      </div>
      <p class="muted" style="margin:0.55rem 0 0">
        抑制数 + 待处置 = 差异合计：{{ data.latest_counts.suppressed }} + {{ data.latest_counts.pending }} = {{ data.latest_counts.diff_total }}。
        被抑制的差异行仍保留在批次与差异清单里，可逐条核对。
      </p>
    </div>

    <div class="panel" v-if="conflict">
      <h3 style="margin-top:0"><span class="tag danger">处置单冲突</span></h3>
      <p>{{ conflict.message }}</p>
      <p class="muted">
        当前策略为「{{ policy === 'reject' ? '拒绝抑制' : '允许抑制并挂起处置单' }}」。
        {{ policy === 'reject'
          ? '如需抑制，请先关闭处置单，或切换为「允许抑制并挂起处置单」。'
          : '该分支本不应出现，请检查策略是否被并发修改。' }}
      </p>
      <p v-if="conflict.diff">
        差异 #{{ conflict.diff.id }} ·
        <span class="mono">{{ JSON.stringify(conflict.diff.align_key) }}</span>
      </p>
    </div>

    <div class="panel" v-if="data">
      <h3 style="margin-top:0">最近批次差异行（按指纹登记）</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>类型</th><th>对齐键</th><th>比对值（左 / 右）</th>
            <th>指纹</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in data.latest_diffs" :key="d.id">
            <td>{{ d.id }}</td>
            <td><span class="tag" :class="kindClass[d.kind]">{{ kindLabel[d.kind] || d.kind }}</span></td>
            <td class="mono">{{ JSON.stringify(d.align_key) }}</td>
            <td class="mono">
              左 {{ d.left ? JSON.stringify(pickValues(d.left)) : '—' }}<br />
              右 {{ d.right ? JSON.stringify(pickValues(d.right)) : '—' }}
            </td>
            <td class="mono" :title="d.fingerprint">{{ (d.fingerprint || '').slice(0, 12) || '—' }}</td>
            <td>
              <span class="tag" :class="stateClass[d.suppression_state] || ''">
                {{ stateLabel[d.suppression_state] || d.suppression_state }}
              </span>
            </td>
            <td>
              <div style="display:flex;flex-wrap:wrap;gap:0.35rem">
                <button
                  :disabled="busy || locked || d.suppression_state === 'suppressed'"
                  @click="policy === 'reject' ? openConflict(d) : enableSuppression(d)"
                >
                  登记抑制
                </button>
                <button class="secondary" :disabled="busy || locked" @click="openTicket(d)">开处置单</button>
                <button
                  class="secondary"
                  :disabled="busy || locked || !d.right"
                  @click="pickSourceRow(d, 'right')"
                >改右端值</button>
                <button
                  class="secondary"
                  :disabled="busy || locked || !d.left"
                  @click="pickSourceRow(d, 'left')"
                >改左端值</button>
              </div>
            </td>
          </tr>
          <tr v-if="!data.latest_diffs.length">
            <td colspan="7" class="muted">本批无差异（或尚未跑对账）。</td>
          </tr>
        </tbody>
      </table>

      <div v-if="changeTarget" class="panel" style="background:#eef3f8">
        <h4 style="margin-top:0">改源值演示（{{ changeTarget.side === 'left' ? '左端' : '右端' }}）</h4>
        <p class="mono">
          {{ JSON.stringify(changeTarget.diff.align_key) }} · 当前行 {{ JSON.stringify(changeTarget.row) }}
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:0.6rem;align-items:flex-end">
          <label>
            比对字段
            <select v-model="changeField" style="display:block;margin-top:0.25rem">
              <option v-for="f in data.pair.compare_fields" :key="f" :value="f">{{ f }}</option>
            </select>
          </label>
          <label>
            新值
            <input v-model="changeValue" style="display:block;width:9rem;margin-top:0.25rem" />
          </label>
          <button :disabled="busy || locked" @click="submitSourceChange">写入运行时夹具</button>
          <button class="secondary" :disabled="busy" @click="changeTarget = null">取消</button>
        </div>
        <p class="muted" style="margin:0.5rem 0 0">
          只改运行时夹具，不碰镜像内基线；改完去「对账台」再跑一趟即可看到抑制失效。
        </p>
      </div>
    </div>

    <div class="panel" v-if="data">
      <h3 style="margin-top:0">抑制登记表（共 {{ data.suppressions.length }} 条，其中生效 {{ data.active_count }} 条）</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>状态</th><th>类型</th><th>对齐键</th><th>比对值</th><th>指纹</th>
            <th>应用次数</th><th>重新激活次数</th><th>处置单策略</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in data.suppressions" :key="s.id">
            <td>{{ s.id }}</td>
            <td>
              <span class="tag" :class="s.status === 'active' ? 'ok' : s.status === 'invalidated' ? 'danger' : ''">
                {{ statusLabel[s.status] || s.status }}
              </span>
            </td>
            <td>{{ kindLabel[s.kind] || s.kind }}</td>
            <td class="mono">{{ JSON.stringify(s.align_key) }}</td>
            <td class="mono">左 {{ s.left_values ? JSON.stringify(s.left_values) : '—' }} / 右 {{ s.right_values ? JSON.stringify(s.right_values) : '—' }}</td>
            <td class="mono" :title="s.fingerprint">{{ s.fingerprint.slice(0, 12) }}</td>
            <td>{{ s.applied_count }}</td>
            <td>{{ s.reactivation_count }}</td>
            <td>{{ s.ticket_policy === 'reject' ? '拒绝抑制' : '允许并挂起' }}</td>
            <td>
              <button
                class="secondary"
                :disabled="busy || locked || s.status !== 'active'"
                @click="revoke(s)"
              >撤销</button>
            </td>
          </tr>
          <tr v-if="!data.suppressions.length">
            <td colspan="10" class="muted">尚无抑制登记。</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel" v-if="data">
      <h3 style="margin-top:0">抑制事件流水</h3>
      <table>
        <thead>
          <tr><th>ID</th><th>动作</th><th>指纹</th><th>批次</th><th>处置单策略</th><th>处置单</th><th>备注</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in data.events" :key="e.id">
            <td>{{ e.id }}</td>
            <td><span class="tag">{{ e.action }}</span></td>
            <td class="mono">{{ e.fingerprint.slice(0, 12) }}</td>
            <td>{{ e.batch_id || '—' }}</td>
            <td>{{ e.ticket_policy || '—' }}</td>
            <td class="mono">{{ e.ticket_ids.length ? '#' + e.ticket_ids.join(', #') : '—' }}</td>
            <td>{{ e.note || '—' }}</td>
            <td class="mono">{{ e.created_at }}</td>
          </tr>
          <tr v-if="!data.events.length"><td colspan="8" class="muted">暂无事件。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
