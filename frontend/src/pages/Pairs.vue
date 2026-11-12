<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const rows = ref([])
const err = ref('')
onMounted(async () => {
  try { rows.value = await getJSON('/api/pairs') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>对账对</h1>
    <p class="muted">每对绑定左右夹具、对齐键与比对字段。增删对与分域深逻辑留给后题。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>编码</th><th>标题</th><th>业务域</th>
            <th>左端</th><th>右端</th><th>对齐键</th><th>比对字段</th><th>启用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in rows" :key="p.id">
            <td>{{ p.id }}</td>
            <td class="mono">{{ p.code }}</td>
            <td>{{ p.title }}</td>
            <td>{{ p.domain }}</td>
            <td>{{ p.left_name }}<div class="mono muted">{{ p.left_fixture }}</div></td>
            <td>{{ p.right_name }}<div class="mono muted">{{ p.right_fixture }}</div></td>
            <td class="mono">{{ p.align_keys.join(' + ') }}</td>
            <td class="mono">{{ p.compare_fields.join(', ') }}</td>
            <td><span class="tag" :class="p.enabled ? 'ok' : 'danger'">{{ p.enabled ? '是' : '否' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
