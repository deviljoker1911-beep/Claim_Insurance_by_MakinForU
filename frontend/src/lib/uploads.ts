/** Client-side checks mirror the API limits; the server remains the authority. */
export const MAX_UPLOAD_MB = 25
export const ACCEPT_ATTRIBUTE = '.pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg'
const ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']

export function precheckFile(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return 'Unsupported file type. Upload PDF, PNG or JPG files.'
  }
  if (file.size === 0) return 'File is empty'
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `File exceeds the ${MAX_UPLOAD_MB} MB limit`
  return null
}
