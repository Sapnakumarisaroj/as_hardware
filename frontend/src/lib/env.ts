/** Browser-visible configuration. Only VITE_* variables reach the bundle — never put secrets here. */
function mapCenter() {
  const [latitude, longitude] = String(import.meta.env.VITE_MAP_CENTER || '')
    .split(',')
    .map((part) => Number(part.trim()))
  if (Number.isFinite(latitude) && Number.isFinite(longitude) && latitude !== undefined && longitude !== undefined) {
    return { latitude, longitude }
  }
  return { latitude: 12.9716, longitude: 77.5946 } // Bengaluru
}

export const env = {
  appName: import.meta.env.VITE_APP_NAME || 'BoltRun',
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/+$/, ''),
  supportPhone: import.meta.env.VITE_SUPPORT_PHONE || '',
  supportWhatsApp: import.meta.env.VITE_SUPPORT_WHATSAPP || '',
  supportEmail: import.meta.env.VITE_SUPPORT_EMAIL || '',
  /** The slim strip above the storefront header; empty hides it. */
  storeHours: import.meta.env.VITE_STORE_HOURS ?? 'Open 8 am to 8 pm all days',
  /** Map tiles for the address pin picker (OpenStreetMap by default; see docs/FREE_TOOLS.md for its usage policy). */
  mapTileUrl: import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  /** Where the map opens when the address has no pin yet: "lat,lng". */
  mapCenter: mapCenter(),
} as const
