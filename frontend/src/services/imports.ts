import { api } from '@/lib/api'
import type { ImportBatch, ImportMode } from '@/types/api'

export interface PreviewOptions {
  file: File
  imagesZip?: File | null
  mode: ImportMode
  allOrNothing: boolean
  initialStatus: 'DRAFT' | 'PENDING'
  allowImageUrls: boolean
}

export async function previewImport(options: PreviewOptions): Promise<ImportBatch> {
  const form = new FormData()
  form.append('file', options.file)
  if (options.imagesZip) form.append('images_zip', options.imagesZip)
  form.append('mode', options.mode)
  form.append('all_or_nothing', String(options.allOrNothing))
  form.append('initial_status', options.initialStatus)
  form.append('allow_image_urls', String(options.allowImageUrls))
  const { data } = await api.post<ImportBatch>('/products/import/preview/', form)
  return data
}

export async function commitImport(id: string): Promise<ImportBatch> {
  const { data } = await api.post<ImportBatch>(`/products/import/${id}/commit/`)
  return data
}

/** Download helpers open the (authenticated, same-session) API URL directly. */
const base = () => (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
export const templateUrl = () => `${base()}/products/import/template/`
export const errorReportUrl = (id: string, type: 'xlsx' | 'csv') => `${base()}/products/import/${id}/errors/?type=${type}`
