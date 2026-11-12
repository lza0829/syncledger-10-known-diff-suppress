<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const rows = ref([])
const err = ref('')
onMounted(async () => {
  try { rows.value = await getJSON('/api/dispositions') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>差异处置</h1>
    <p class="muted">对账差异处置单表已就位。挂差异、认领、回灌复核留给后题切口；当前为空列表属预期。不是客服工单台。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead><tr><th>ID</th><th>标题</th><th>状态</th><th>处理人</th><th>备注</th><th>更新</th></tr></thead>
        <tbody>
          <tr v-for="t in rows" :key="t.id">
            <td>{{ t.id }}</td>
            <td>{{ t.title }}</td>
            <td>{{ t.status }}</td>
            <td>{{ t.assignee || '—' }}</td>
            <td>{{ t.note || '—' }}</td>
            <td class="mono">{{ t.updated_at }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="6" class="muted">暂无差异处置单。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
