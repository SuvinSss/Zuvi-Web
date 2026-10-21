import axios from 'axios'
import { api } from '@/lib/api'
import type { NeedsMapping } from '@/types/management'
import type { ImportBatch, ImportMode } from '@/types/api'

export interface PreviewOptions {
  file: File
  imagesZip?: File | null
  mode: ImportMode
  allOrNothing: boolean
  initialStatus: 'DRAFT' | 'PENDING'
  allowImageUrls: boolean
  mapping?: Record<string, string>
  defaultStoreCode?: string
  generateSku?: boolean
}

export async function previewImport(options: PreviewOptions): Promise<ImportBatch> {
  const form = new FormData()
  form.append('file', options.file)
  if (options.imagesZip) form.append('images_zip', options.imagesZip)
  form.append('mode', options.mode)
  form.append('all_or_nothing', String(options.allOrNothing))
  form.append('initial_status', options.initialStatus)
  form.append('allow_image_urls', String(options.allowImageUrls))
  if (options.mapping && Object.keys(options.mapping).length) form.append('mapping', JSON.stringify(options.mapping))
  if (options.defaultStoreCode) form.append('default_store_code', options.defaultStoreCode)
  form.append('generate_sku', String(options.generateSku ?? true))
  try {
    const { data } = await api.post<ImportBatch>('/products/import/preview/', form)
    return data
  } catch (error) {
    // 422 means "I could not tell which column is which", not a broken file: show the mapping screen.
    if (axios.isAxiosError(error) && error.response?.status === 422 && error.response.data?.needs_mapping) throw new MappingRequired(error.response.data as NeedsMapping)
    throw error
  }
}

export class MappingRequired extends Error {
  info: NeedsMapping
  constructor(info: NeedsMapping) { super(info.detail); this.info = info }
}

export async function commitImport(id: string): Promise<ImportBatch> {
  const { data } = await api.post<ImportBatch>(`/products/import/${id}/commit/`)
  return data
}

/** Download helpers open the (authenticated, same-session) API URL directly. */
const base = () => (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
export const templateUrl = () => `${base()}/products/import/template/`
export const errorReportUrl = (id: string, type: 'xlsx' | 'csv') => `${base()}/products/import/${id}/errors/?type=${type}`
