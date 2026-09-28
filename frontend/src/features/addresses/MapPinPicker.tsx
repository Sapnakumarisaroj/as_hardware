import 'leaflet/dist/leaflet.css'

import L from 'leaflet'
import { useEffect, useRef } from 'react'

import { env } from '@/lib/env'

export interface LatLng {
  latitude: number
  longitude: number
}

// A drawn pin: Leaflet's default marker images need bundler-specific asset handling.
const PIN = L.divIcon({
  className: '',
  iconSize: [32, 40],
  iconAnchor: [16, 38],
  html:
    '<svg viewBox="0 0 24 30" width="32" height="40" aria-hidden="true">' +
    '<path d="M12 29S2 19.5 2 11.5a10 10 0 0 1 20 0C22 19.5 12 29 12 29Z" fill="#d97706" stroke="#fff" stroke-width="1.5"/>' +
    '<circle cx="12" cy="11.5" r="3.5" fill="#fff"/></svg>',
})

/**
 * OpenStreetMap map (Leaflet) for marking the exact delivery spot: tap the map or drag the pin.
 * Loaded only when the customer opens it (see AddressLocationField), so Leaflet stays out of
 * the main bundle. Keyboard users can use the arrow keys to move the focused pin's map and
 * can always skip the map: the PIN code alone is enough to deliver.
 */
export default function MapPinPicker({
  value,
  center,
  onChange,
}: {
  value: LatLng | null
  center: LatLng
  onChange: (value: LatLng) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const marker = useRef<L.Marker | null>(null)
  const map = useRef<L.Map | null>(null)
  const changed = useRef(onChange)
  useEffect(() => {
    changed.current = onChange
  }, [onChange])

  useEffect(() => {
    if (!container.current) return
    const start = value ?? center
    const instance = L.map(container.current, { scrollWheelZoom: false }).setView(
      [start.latitude, start.longitude],
      value ? 16 : 12,
    )
    L.tileLayer(env.mapTileUrl, {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(instance)

    const place = (at: L.LatLng) => {
      if (marker.current) marker.current.setLatLng(at)
      else {
        marker.current = L.marker(at, { icon: PIN, draggable: true, keyboard: true, alt: 'Delivery location' }).addTo(instance)
        marker.current.on('dragend', () => {
          const moved = marker.current!.getLatLng()
          changed.current({ latitude: moved.lat, longitude: moved.lng })
        })
      }
    }
    if (value) place(L.latLng(value.latitude, value.longitude))
    instance.on('click', (event: L.LeafletMouseEvent) => {
      place(event.latlng)
      changed.current({ latitude: event.latlng.lat, longitude: event.latlng.lng })
    })
    map.current = instance
    return () => {
      instance.remove()
      map.current = null
      marker.current = null
    }
    // The map is created once; later value changes are applied by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!map.current || !value) return
    const at = L.latLng(value.latitude, value.longitude)
    if (marker.current && marker.current.getLatLng().equals(at)) return
    if (marker.current) marker.current.setLatLng(at)
    map.current.setView(at, Math.max(map.current.getZoom(), 16))
  }, [value])

  return <div ref={container} className="h-64 w-full rounded-md ring-1 ring-steel-200" role="application" aria-label="Map: choose the delivery location" />
}
