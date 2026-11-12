<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const batches = ref([])
const batchId = ref(null)
const summary = ref(null)
const err = ref('')

async function loadBatches() {
  batches.value = await getJSON('/api/batches?limit=30')
  if (route.query.batch_id) batchId.value = Number(route.query.batch_id)
  else if (!batchId.value && batches.value.length) batchId.value = batches.value[0].id
}

async function loadSummary() {
  summary.value = null
  if (!batchId.value) return
  summary.value = await getJSON(`/api/audit/batches/${batchId.value}`)
}

onMounted(async () => {
  try {
    await loadBatches()
    await loadSummary()
  } catch (e) { err.value = String(e.message || e) }
})
watch(batchId, async () => {
  try { await loadSummary() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>审计摘要</h1>
    <p class="muted">按批次查看快照计数。导出包与清单哈希留给后题；当前 export_ready=false。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <label>
        批次
        <select v-model.number="batchId" style="display:block;margin-top:0.35rem;min-width:20rem">
          <option v-for="b in batches" :key="b.id" :value="b.id">{{ b.batch_no }} · {{ b.pair_title }}</option>
        </select>
      </label>
    </div>
    <div class="panel" v-if="summary">
      <p>批次 <span class="mono">{{ summary.batch.batch_no }}</span> · {{ summary.pair?.title }}</p>
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ summary.diff_count }}</div><div class="stat-label">差异行</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.left_only }}</div><div class="stat-label">仅左有</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.right_only }}</div><div class="stat-label">仅右有</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.field_mismatch }}</div><div class="stat-label">字段不一致</div></div>
      </div>
      <p style="margin-top:0.85rem" class="muted">{{ summary.note }}</p>
      <p>可导出 <span class="tag" :class="summary.export_ready ? 'ok' : 'warn'">{{ summary.export_ready ? '是' : '否' }}</span></p>
    </div>
  </div>
</template>
