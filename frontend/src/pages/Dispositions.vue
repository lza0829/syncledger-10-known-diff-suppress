<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'

const rows = ref([])
const err = ref('')
const statusClass = {
  open: 'warn',
  claimed: 'warn',
  in_progress: 'warn',
  suspended_by_suppression: 'ok',
  closed: '',
}
const statusLabel = {
  open: '未关',
  claimed: '已认领',
  in_progress: '处理中',
  suspended_by_suppression: '抑制挂起',
  closed: '已关',
}

onMounted(async () => {
  try { rows.value = await getJSON('/api/dispositions') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>差异处置</h1>
    <p class="muted">
      对账差异处置单。与「已知差异抑制」联动：策略为「拒绝抑制」时，未关处置单阻止登记；
      策略为「允许抑制并自动挂起」时，未关处置单被置为 <span class="mono">suspended_by_suppression</span>。
      抑制失效或被撤销时，挂起处置单恢复未关。不是客服工单台。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>标题</th><th>状态</th><th>差异行</th><th>差异类型</th>
            <th>对齐键</th><th>处理人</th><th>备注</th><th>更新</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in rows" :key="t.id">
            <td>{{ t.id }}</td>
            <td>{{ t.title }}</td>
            <td><span class="tag" :class="statusClass[t.status] || ''">{{ statusLabel[t.status] || t.status }}</span></td>
            <td>{{ t.diff_id || '—' }}</td>
            <td>{{ t.diff_kind || '—' }}</td>
            <td class="mono">{{ t.align_key ? JSON.stringify(t.align_key) : '—' }}</td>
            <td>{{ t.assignee || '—' }}</td>
            <td>{{ t.note || '—' }}</td>
            <td class="mono">{{ t.updated_at }}</td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="9" class="muted">暂无差异处置单。可在「已知差异抑制」页对差异行开处置单，演示冲突。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
