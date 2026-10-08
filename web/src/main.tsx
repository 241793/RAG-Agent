import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 0, refetchOnWindowFocus: false } } })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: theme.defaultAlgorithm,
          token: {
            colorPrimary: '#2563eb',
            colorInfo: '#2563eb',
            borderRadius: 8,
            colorBgLayout: '#f5f7fa',
            fontSize: 14,
            fontFamily:
              'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
          },
          components: {
            Layout: { headerBg: '#ffffff', headerHeight: 56, siderBg: '#ffffff', bodyBg: '#f5f7fa' },
            Menu: { itemBorderRadius: 8, itemMarginInline: 8, itemHeight: 40 },
            Card: { borderRadiusLG: 12 },
            Table: { headerBg: '#fafbfc', headerColor: '#1f2937' },
            Button: { borderRadius: 8 },
          },
        }}
      >
        <AntApp>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
