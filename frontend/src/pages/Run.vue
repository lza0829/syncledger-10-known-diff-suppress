<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const pairs = ref([])
const batches = ref([])
const pairId = ref(null)
const note = ref('')
const last = ref(null)
const busy = ref(false)
const err = ref('')

async function refresh() {
  pairs.value = await getJSON('/api/pairs')
  batches.value = await getJSON('/api/batches?limit=20')
  if (pairId.value == null && pairs.value.length) pairId.value = pairs.value[0].id
}

async function run() {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON('/api/reconcile', { pair_id: Number(pairId.value), note: note.value || null })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>对账台</h1>
    <p class="muted">选一对账对，抽取左右夹具并对齐。底座策略：只落差异，不自动盖写任何一端。</p>
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
        <button :disabled="busy || !pairId" @click="run">{{ busy ? '对账中…' : '抽取并对齐' }}</button>
      </div>
    </div>

    <div class="panel" v-if="last">
      <h3 style="margin-top:0">最近一趟</h3>
      <p>
        批次 <span class="mono">{{ last.batch_no }}</span> · {{ last.pair_title }} ·
        <span class="tag ok">{{ last.status }}</span>
      </p>
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ last.matched }}</div><div class="stat-label">一致</div></div>
        <div class="stat"><div class="stat-num">{{ last.left_only }}</div><div class="stat-label">仅左有</div></div>
        <div class="stat"><div class="stat-num">{{ last.right_only }}</div><div class="stat-label">仅右有</div></div>
        <div class="stat"><div class="stat-num">{{ last.field_mismatch }}</div><div class="stat-label">字段不一致</div></div>
        <div class="stat"><div class="stat-num">{{ last.diff_total }}</div><div class="stat-label">差异合计</div></div>
      </div>
      <p style="margin-top:0.75rem">
        <router-link :to="{ path: '/diffs', query: { batch_id: last.id } }">查看本批差异 →</router-link>
        ·
        <router-link :to="{ path: '/audit', query: { batch_id: last.id } }">审计摘要 →</router-link>
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">历史批次</h3>
      <table>
        <thead>
          <tr>
            <th>批次</th><th>对账对</th><th>状态</th>
            <th>左/右行</th><th>一致</th><th>仅左</th><th>仅右</th><th>字段差</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td>{{ b.pair_title }}</td>
            <td><span class="tag ok">{{ b.status }}</span></td>
            <td class="mono">{{ b.left_rows }} / {{ b.right_rows }}</td>
            <td>{{ b.matched }}</td>
            <td>{{ b.left_only }}</td>
            <td>{{ b.right_only }}</td>
            <td>{{ b.field_mismatch }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
          <tr v-if="!batches.length"><td colspan="9" class="muted">还没有批次，先跑一趟。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
