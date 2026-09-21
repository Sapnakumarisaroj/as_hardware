/** Browser-visible configuration. Only VITE_* variables reach the bundle — never put secrets here. */
export const env = {
  appName: import.meta.env.VITE_APP_NAME || 'BoltRun',
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/+$/, ''),
  supportPhone: import.meta.env.VITE_SUPPORT_PHONE || '',
  supportWhatsApp: import.meta.env.VITE_SUPPORT_WHATSAPP || '',
} as const
