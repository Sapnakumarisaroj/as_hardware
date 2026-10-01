/** Checks a chosen photo in the browser and makes it smaller before upload (phones take 4–12 MB photos).

The server checks everything again; this only gives faster, friendlier answers and saves mobile data. */

export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_SIDE = 1600

export function problemWith(file: File, maxBytes: number): string | null {
  const type = file.type.toLowerCase()
  if (type === 'image/heic' || type === 'image/heif' || /\.hei[cf]$/i.test(file.name)) {
    return 'HEIC photos can’t be read here. Take the photo with the button above, or choose a JPEG or PNG.'
  }
  if (type && !ACCEPTED_TYPES.includes(type)) return 'Choose a JPEG, PNG or WebP photo.'
  if (file.size === 0) return 'That file is empty.'
  if (file.size > maxBytes) return `That photo is too large (${Math.round(maxBytes / (1024 * 1024))} MB at most).`
  return null
}

/** A JPEG at most MAX_SIDE pixels wide/high, or the original file when the browser can't resize it. */
export async function shrink(file: File): Promise<File> {
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
    if (scale === 1 && file.size < 1.5 * 1024 * 1024) {
      bitmap.close()
      return file
    }
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const context = canvas.getContext('2d')
    if (!context) return file
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close()
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85))
    if (!blob) return file
    return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' })
  } catch {
    return file // unreadable here: let the server decide (it gives a clear message)
  }
}
