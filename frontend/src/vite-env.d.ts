/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_APP_NAME?: string
  readonly VITE_SUPPORT_PHONE?: string
  readonly VITE_SUPPORT_WHATSAPP?: string
  readonly VITE_SUPPORT_EMAIL?: string
  readonly VITE_MAP_TILE_URL?: string
  readonly VITE_MAP_CENTER?: string
  readonly VITE_STORE_HOURS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
