import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './pages/Dashboard.vue'
import Pairs from './pages/Pairs.vue'
import Run from './pages/Run.vue'
import Diffs from './pages/Diffs.vue'
import Dispositions from './pages/Dispositions.vue'
import Contracts from './pages/Contracts.vue'
import Audit from './pages/Audit.vue'
import Settings from './pages/Settings.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/pairs', component: Pairs },
    { path: '/run', component: Run },
    { path: '/diffs', component: Diffs },
    { path: '/dispositions', component: Dispositions },
    { path: '/contracts', component: Contracts },
    { path: '/audit', component: Audit },
    { path: '/settings', component: Settings },
  ],
})
