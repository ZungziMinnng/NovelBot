import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { useAuthStore } from './store/authStore'
import { useBrainstormStore } from './store/brainstormStore'
import { useDevLogStore } from './store/devLogStore'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1000 * 30, retry: 1 },
  },
})

// 登出、登录过期、换号登录都不刷新页面，查询缓存会原样留到下一个账号手里：
// 小说列表 30 秒内、staleTime: Infinity 的那几处永远显示上一个人的数据。
// 所以 token 一变就整个扔掉
useAuthStore.subscribe((state, prev) => {
  if (state.token !== prev.token) {
    queryClient.clear()
    // 开发日志面板里是原样的请求/响应体
    useDevLogStore.getState().clear()
  }
  // 构思对话存在 localStorage 且不分小说、不分账号，换了人得清掉。
  // 老版本存下来的状态没有 lastUserId（undefined），不算换人
  if (state.user && prev.lastUserId != null && state.user.id !== prev.lastUserId) {
    useBrainstormStore.getState().clearConversation()
  }
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
)
