<template>
  <div class="layout">
    <aside class="rail">
      <div class="brand">双核<br />Syncledger</div>
      <router-link to="/">总览</router-link>
      <router-link to="/pairs">对账对</router-link>
      <router-link to="/run">对账台</router-link>
      <router-link to="/diffs">差异清单</router-link>
      <router-link to="/dispositions">差异处置</router-link>
      <router-link to="/contracts">端契约</router-link>
      <router-link to="/audit">审计摘要</router-link>
      <router-link to="/settings">设置</router-link>
    </aside>
    <main><router-view /></main>
  </div>
</template>
