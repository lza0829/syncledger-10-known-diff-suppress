<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const rows = ref([])
const err = ref('')
const kindClass = { left_only: 'warn', right_only: 'warn', field_mismatch: 'danger' }
const kindLabel = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }

async function refresh() {
  const q = route.query.batch_id ? `?batch_id=${route.query.batch_id}` : ''
  rows.value = await getJSON(`/api/diffs${q}`)
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
    <div class="panel">
      <table>
        <thead>
          <tr><th>ID</th><th>批次</th><th>类型</th><th>对齐键</th><th>不一致字段</th><th>左</th><th>右</th></tr>
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
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="muted">暂无差异。去对账台跑一趟后回到这里。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
