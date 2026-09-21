/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_APP_NAME?: string
  readonly VITE_SUPPORT_PHONE?: string
  readonly VITE_SUPPORT_WHATSAPP?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
