<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const settings = ref({})
const err = ref('')
onMounted(async () => {
  try { settings.value = await getJSON('/api/settings') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>设置</h1>
    <p class="muted">全局策略键值。自动盖写默认关闭；主从取舍等策略留给后题。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead><tr><th>键</th><th>值</th></tr></thead>
        <tbody>
          <tr v-for="(v, k) in settings" :key="k">
            <td class="mono">{{ k }}</td>
            <td class="mono">{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
