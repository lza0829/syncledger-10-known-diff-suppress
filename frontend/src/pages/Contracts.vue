<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const rows = ref([])
const err = ref('')
onMounted(async () => {
  try { rows.value = await getJSON('/api/contracts') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>端契约</h1>
    <p class="muted">左右端字段清单种子。漂移拦截与兼容策略留给后题。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead><tr><th>对账对</th><th>端</th><th>版本</th><th>字段</th><th>更新</th></tr></thead>
        <tbody>
          <tr v-for="c in rows" :key="c.id">
            <td class="mono">{{ c.pair_code }}</td>
            <td>{{ c.side === 'left' ? '左端' : '右端' }}</td>
            <td>{{ c.version }}</td>
            <td class="mono">{{ c.fields.join(', ') }}</td>
            <td class="mono">{{ c.updated_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
