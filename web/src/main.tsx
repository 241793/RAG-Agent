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
            colorSuccess: '#10b981',
            colorWarning: '#f59e0b',
            colorError: '#ef4444',
            colorTextBase: '#0f172a',
            colorBgLayout: '#f8fafc',
            colorBorder: '#e2e8f0',
            borderRadius: 8,
            fontSize: 14,
            fontFamily:
              '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
          },
          components: {
            Layout: {
              headerBg: '#ffffff',
              headerHeight: 56,
              siderBg: '#ffffff',
              bodyBg: '#f8fafc',
            },
            Menu: {
              itemBorderRadius: 8,
              itemMarginInline: 6,
              itemHeight: 38,
              itemSelectedBg: '#eff6ff',
              itemSelectedColor: '#1d4ed8',
            },
            Card: {
              borderRadiusLG: 12,
            },
            Table: {
              headerBg: '#f8fafc',
              headerColor: '#475569',
              borderColor: '#e2e8f0',
            },
            Button: {
              borderRadius: 8,
              controlHeight: 36,
            },
            Input: {
              borderRadius: 8,
            },
            Select: {
              borderRadius: 8,
            },
            Modal: {
              borderRadiusLG: 14,
            },
            Drawer: {
              borderRadiusLG: 14,
            },
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
