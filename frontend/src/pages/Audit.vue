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
    <p class="muted">
      按批次查看快照计数。已知差异抑制不改写历史批次：被抑制行仍在差异行计数中，单列为「抑制数」。
      导出包与清单哈希留给后题；当前 export_ready=false。
    </p>
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
      <p>
        批次 <span class="mono">{{ summary.batch.batch_no }}</span> · {{ summary.pair?.title }} ·
        <span class="tag" :class="summary.batch.status === 'completed' ? 'ok' : 'warn'">{{ summary.batch.status }}</span>
      </p>
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ summary.diff_count }}</div><div class="stat-label">差异行</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.left_only }}</div><div class="stat-label">仅左有</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.right_only }}</div><div class="stat-label">仅右有</div></div>
        <div class="stat"><div class="stat-num">{{ summary.kinds.field_mismatch }}</div><div class="stat-label">字段不一致</div></div>
        <div class="stat"><div class="stat-num">{{ summary.suppression.suppressed }}</div><div class="stat-label">抑制数</div></div>
        <div class="stat"><div class="stat-num">{{ summary.suppression.reactivated }}</div><div class="stat-label">重新激活数</div></div>
        <div class="stat"><div class="stat-num">{{ summary.suppression.pending }}</div><div class="stat-label">待处置</div></div>
      </div>
      <p style="margin-top:0.85rem">
        一致性核对
        <span class="tag" :class="summary.consistency.consistent ? 'ok' : 'danger'">
          {{ summary.consistency.consistent ? '通过' : '不一致' }}
        </span>
      </p>
      <table>
        <thead><tr><th>核对项</th><th>结果</th></tr></thead>
        <tbody>
          <tr v-for="(v, k) in summary.consistency.checks" :key="k">
            <td class="mono">{{ k }}</td>
            <td><span class="tag" :class="v ? 'ok' : 'danger'">{{ v ? '通过' : '不通过' }}</span></td>
          </tr>
        </tbody>
      </table>
      <h3>抑制应用明细</h3>
      <table>
        <thead>
          <tr><th>差异行</th><th>状态</th><th>类型</th><th>对齐键</th><th>指纹</th><th>抑制登记</th><th>重新激活自</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in summary.suppression_applications" :key="a.id">
            <td>{{ a.diff_id }}</td>
            <td>
              <span class="tag" :class="a.fingerprint_state === 'suppressed' ? 'ok' : 'danger'">
                {{ a.fingerprint_state === 'suppressed' ? '已抑制' : '重新激活' }}
              </span>
            </td>
            <td>{{ a.kind }}</td>
            <td class="mono">{{ JSON.stringify(a.align_key) }}</td>
            <td class="mono" :title="a.fingerprint">{{ a.fingerprint.slice(0, 12) }}</td>
            <td>{{ a.suppression_id || '—' }}</td>
            <td>{{ a.reactivates_suppression_id || '—' }}</td>
          </tr>
          <tr v-if="!summary.suppression_applications.length">
            <td colspan="7" class="muted">本批没有抑制命中或失效。</td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:0.85rem" class="muted">{{ summary.note }}</p>
      <p>可导出 <span class="tag" :class="summary.export_ready ? 'ok' : 'warn'">{{ summary.export_ready ? '是' : '否' }}</span></p>
    </div>
  </div>
</template>
