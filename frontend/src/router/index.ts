import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
    history: createWebHistory(),
    routes: [
        { path: '/login', component: () => import('../views/Login.vue') },
        {
            path: '/',
            component: () => import('../layouts/MainLayout.vue'),
            children: [
                { path: '', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
                { path: 'personnel', name: 'Personnel', component: () => import('../views/Personnel.vue') },
                { path: 'cards', name: 'Cards', component: () => import('../views/Cards.vue') },
                { path: 'shifts', name: 'Shifts', component: () => import('../views/Shifts.vue') },
                { path: 'records', name: 'Records', component: () => import('../views/Records.vue') },
            ]
        }
    ]
})

// 簡單的路由守衛
router.beforeEach((to, from, next) => {
    const isAuthenticated = !!localStorage.getItem('token')
    if (to.path !== '/login' && !isAuthenticated) {
        next('/login')
    } else {
        next()
    }
})

export default router
