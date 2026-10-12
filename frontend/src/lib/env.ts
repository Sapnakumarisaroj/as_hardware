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
  appName: import.meta.env.VITE_APP_NAME || 'AS Hardware and Plywood',
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/+$/, ''),
  supportPhone: import.meta.env.VITE_SUPPORT_PHONE || '7338192616',
  supportWhatsApp: import.meta.env.VITE_SUPPORT_WHATSAPP || '917338192616',
  supportEmail: import.meta.env.VITE_SUPPORT_EMAIL || 'ashardwareplywood@gmail.com',
  /** Sign-in by SMS code: off until a real SMS gateway is live (the server's OTP_LOGIN_ENABLED must match). */
  otpLoginEnabled: import.meta.env.VITE_OTP_LOGIN_ENABLED === 'true',
  /** The slim strip above the storefront header; empty hides it. */
  /** Map tiles for the address pin picker (OpenStreetMap by default; see docs/FREE_TOOLS.md for its usage policy). */
  mapTileUrl: import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  /** Where the map opens when the address has no pin yet: "lat,lng". */
  mapCenter: mapCenter(),
} as const
