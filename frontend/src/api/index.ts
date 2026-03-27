import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
    baseURL: '/api/v1',
    timeout: 5000
})

// 請求攔截器：自動帶入 JWT Token
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token')
    if (token && config.headers) {
        config.headers.Authorization = `Bearer ${token}`
    }
    return config
})

// 回應攔截器：統一處理錯誤
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            ElMessage.error('登入逾時，請重新登入')
            localStorage.removeItem('token')
            // 只有當前不在登入頁時才跳轉，避免無窮導向
            if (window.location.pathname !== '/login') {
                window.location.href = '/login'
            }
        } else {
            ElMessage.error(error.response?.data?.detail || '系統錯誤')
        }
        return Promise.reject(error)
    }
)

export default api
