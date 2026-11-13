<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getJSON, postJSON } from '../api'

const pairs = ref([])
const batches = ref([])
const pairId = ref(null)
const note = ref('')
const holdMs = ref(0)
const last = ref(null)
const busy = ref(false)
const err = ref('')
const sourceState = ref(null)

const running = computed(() => !!last.value && ['extracting', 'aligning'].includes(last.value.status))
let pollTimer = null

function schedulePoll() {
  if (pollTimer || !running.value) return
  pollTimer = setTimeout(async () => {
    pollTimer = null
    try {
      await refresh()
    } catch (e) {
      err.value = String(e.message || e)
    }
    schedulePoll()
  }, 700)
}

watch(running, () => schedulePoll())
onBeforeUnmount(() => { if (pollTimer) clearTimeout(pollTimer) })


async function refresh() {
  pairs.value = await getJSON('/api/pairs')
  batches.value = await getJSON('/api/batches?limit=20')
  if (pairId.value == null && pairs.value.length) pairId.value = pairs.value[0].id
  if (last.value) {
    last.value = await getJSON(`/api/batches/${last.value.id}`)
  } else if (batches.value.length) {
    last.value = await getJSON(`/api/batches/${batches.value[0].id}`)
  }
  if (pairId.value != null) sourceState.value = await getJSON(`/api/demo/source-state?pair_id=${pairId.value}`)
}

async function run() {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON('/api/reconcile', {
      pair_id: Number(pairId.value),
      note: note.value || null,
      hold_ms: Number(holdMs.value) || 0,
    })
    await refresh()
    schedulePoll()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function resetSource() {
  err.value = ''
  try {
    await postJSON('/api/demo/source-reset', { pair_id: Number(pairId.value) })
    await refresh()
  } catch (e) { err.value = String(e.message || e) }
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>对账台</h1>
    <p class="muted">
      选一对账对，抽取左右夹具并对齐。底座策略：只落差异，不自动盖写任何一端。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>

    <div class="panel">
      <h3 style="margin-top:0">发起对账</h3>
      <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
        <label>
          对账对
          <select v-model.number="pairId" style="display:block;min-width:18rem;margin-top:0.25rem">
            <option v-for="p in pairs" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
        </label>
        <label>
          备注（可选）
          <input v-model="note" style="display:block;width:16rem;margin-top:0.25rem" placeholder="本趟说明" />
        </label>
        <label>
          演示：抽取/对齐停留毫秒
          <input v-model.number="holdMs" type="number" min="0" max="20000" step="500"
                 style="display:block;width:9rem;margin-top:0.25rem" />
        </label>
        <button :disabled="busy || !pairId || running" @click="run">
          {{ running ? '对账进行中…' : busy ? '提交中…' : '抽取并对齐' }}
        </button>
        <button class="secondary" :disabled="!pairId" @click="resetSource">还原源夹具</button>
      </div>
      <p class="muted" style="margin:0.6rem 0 0">
        对账处于抽取或对齐阶段时，抑制登记/撤销会被拒绝，避免本趟统计中途被改。
      </p>
      <p class="muted" style="margin:0.3rem 0 0" v-if="sourceState">
        源侧状态：
        <span class="tag" :class="sourceState.changed ? 'warn' : 'ok'">
          {{ sourceState.changed ? '源夹具已改动' : '与基线一致' }}
        </span>
        <span class="mono" style="margin-left:0.5rem">
          左 {{ sourceState.left.current_digest?.slice(0, 10) }} ·
          右 {{ sourceState.right.current_digest?.slice(0, 10) }}
        </span>
      </p>
    </div>

    <div class="panel" v-if="last">
      <h3 style="margin-top:0">最近一趟</h3>
      <p>
        批次 <span class="mono">{{ last.batch_no }}</span> · {{ last.pair_title }} ·
        <span class="tag" :class="running ? 'warn' : 'ok'">{{ last.status }}</span>
      </p>
      <div class="stat-grid" v-if="last.status === 'completed'">
        <div class="stat"><div class="stat-num">{{ last.matched }}</div><div class="stat-label">一致</div></div>
        <div class="stat"><div class="stat-num">{{ last.left_only }}</div><div class="stat-label">仅左有</div></div>
        <div class="stat"><div class="stat-num">{{ last.right_only }}</div><div class="stat-label">仅右有</div></div>
        <div class="stat"><div class="stat-num">{{ last.field_mismatch }}</div><div class="stat-label">字段不一致</div></div>
        <div class="stat"><div class="stat-num">{{ last.diff_total }}</div><div class="stat-label">差异合计</div></div>
        <div class="stat"><div class="stat-num">{{ last.suppressed_count }}</div><div class="stat-label">抑制数</div></div>
        <div class="stat"><div class="stat-num">{{ last.reactivated_count }}</div><div class="stat-label">重新激活</div></div>
        <div class="stat"><div class="stat-num">{{ last.pending_count }}</div><div class="stat-label">待处置</div></div>
      </div>
      <p class="muted" v-else>抽取/对齐进行中，抑制登记与撤销已暂时禁止。</p>
      <p style="margin-top:0.75rem">
        <router-link :to="{ path: '/diffs', query: { batch_id: last.id } }">查看本批差异 →</router-link>
        ·
        <router-link :to="{ path: '/audit', query: { batch_id: last.id } }">审计摘要 →</router-link>
        ·
        <router-link :to="{ path: '/suppressions', query: { pair_id: last.pair_id } }">已知差异抑制 →</router-link>
      </p>
      <p class="muted" style="margin:0.4rem 0 0">
        抑制数 + 待处置 = 差异合计（{{ last.suppressed_count }} + {{ last.pending_count }} = {{ last.diff_total }}）；
        被抑制的差异行仍保留在批次与差异清单中。
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">历史批次</h3>
      <table>
        <thead>
          <tr>
            <th>批次</th><th>对账对</th><th>状态</th>
            <th>左/右行</th><th>一致</th><th>仅左</th><th>仅右</th><th>字段差</th>
            <th>差异合计</th><th>抑制</th><th>重新激活</th><th>待处置</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td>{{ b.pair_title }}</td>
            <td><span class="tag" :class="b.status === 'completed' ? 'ok' : 'warn'">{{ b.status }}</span></td>
            <td class="mono">{{ b.left_rows }} / {{ b.right_rows }}</td>
            <td>{{ b.matched }}</td>
            <td>{{ b.left_only }}</td>
            <td>{{ b.right_only }}</td>
            <td>{{ b.field_mismatch }}</td>
            <td>{{ b.diff_total }}</td>
            <td>{{ b.suppressed_count }}</td>
            <td>{{ b.reactivated_count }}</td>
            <td>{{ b.pending_count }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
          <tr v-if="!batches.length"><td colspan="13" class="muted">还没有批次，先跑一趟。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
