<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const rows = ref([])
const err = ref('')
const batch = ref(null)

const kindClass = { left_only: 'warn', right_only: 'warn', field_mismatch: 'danger' }
const kindLabel = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }
const stateLabel = { pending: '待处置', suppressed: '已抑制', reactivated: '重新激活' }
const stateClass = { pending: 'warn', suppressed: 'ok', reactivated: 'danger' }

async function refresh() {
  const q = route.query.batch_id ? `?batch_id=${route.query.batch_id}` : ''
  rows.value = await getJSON(`/api/diffs${q}`)
  batch.value = null
  if (rows.value.length) {
    batch.value = await getJSON(`/api/batches/${rows.value[0].batch_id}`)
  }
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
watch(() => route.query.batch_id, async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>差异清单</h1>
    <p class="muted">
      对齐后的差异行。底座只记账；主从盖写、忽略规则、严重级别闸留给后题。
      <span v-if="route.query.batch_id">当前过滤批次 #{{ route.query.batch_id }}</span>
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>

    <div class="panel" v-if="batch">
      <p style="margin:0">
        批次 <span class="mono">{{ batch.batch_no }}</span> ·
        差异合计 {{ batch.diff_total }} ·
        <span class="tag ok">抑制 {{ batch.suppressed_count }}</span> ·
        <span class="tag danger">重新激活 {{ batch.reactivated_count }}</span> ·
        <span class="tag warn">待处置 {{ batch.diff_total - batch.suppressed_count }}</span>
      </p>
      <p class="muted" style="margin:0.4rem 0 0">
        被抑制的差异行照样保留在清单里（不从批次报告中消失），因此抑制数与待处置数之和等于差异合计。
      </p>
    </div>

    <div class="panel">
      <table>
        <thead>
          <tr><th>ID</th><th>批次</th><th>类型</th><th>对齐键</th><th>不一致字段</th><th>左</th><th>右</th><th>抑制状态</th><th>指纹</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id">
            <td>{{ d.id }}</td>
            <td>{{ d.batch_id }}</td>
            <td><span class="tag" :class="kindClass[d.kind]">{{ kindLabel[d.kind] || d.kind }}</span></td>
            <td class="mono">{{ JSON.stringify(d.align_key) }}</td>
            <td class="mono">{{ (d.mismatched_fields || []).join(', ') || '—' }}</td>
            <td class="mono">{{ d.left ? JSON.stringify(d.left) : '—' }}</td>
            <td class="mono">{{ d.right ? JSON.stringify(d.right) : '—' }}</td>
            <td><span class="tag" :class="stateClass[d.suppression_state] || ''">{{ stateLabel[d.suppression_state] || d.suppression_state || '—' }}</span></td>
            <td class="mono" :title="d.fingerprint">{{ (d.fingerprint || '').slice(0, 12) || '—' }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="9" class="muted">暂无差异。去对账台跑一趟后回到这里。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
