import { api } from '@/lib/api'
import type { Meta, Page, ProductDetail, ProductImageRecord, ProductListItem, ProductWritePayload } from '@/types/api'

export type ProductScope = 'admin' | 'store'
const root = (scope: ProductScope) => (scope === 'store' ? '/store/products' : '/products')

export interface ProductQuery {
  q?: string
  status?: string
  category?: string
  store?: string
  has_image?: string
  ordering?: string
  page?: number
  page_size?: number
}

export async function listProducts(query: ProductQuery, signal?: AbortSignal): Promise<Page<ProductListItem>> {
  const params = Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined && v !== ''))
  const { data } = await api.get<Page<ProductListItem>>('/products/', { params, signal })
  return data
}

export async function getProduct(id: number, scope: ProductScope = 'admin'): Promise<ProductDetail> {
  const { data } = await api.get<ProductDetail>(`${root(scope)}/${id}/`)
  return data
}

export async function createProduct(payload: ProductWritePayload, scope: ProductScope = 'admin'): Promise<ProductDetail> {
  const { data } = await api.post<ProductDetail>(`${root(scope)}/`, payload)
  return data
}

export async function updateProduct(id: number, payload: Partial<ProductWritePayload>, scope: ProductScope = 'admin'): Promise<ProductDetail> {
  const { data } = await api.patch<ProductDetail>(`${root(scope)}/${id}/`, payload)
  return data
}

export async function getMeta(scope: ProductScope = 'admin'): Promise<Meta> {
  if (scope === 'store') {
    const { data } = await api.get<Omit<Meta, 'stores' | 'statuses' | 'can'> & { can: { manage_inventory: boolean } }>('/store/meta/')
    return { ...data, stores: [], statuses: [], can: { view: true, add: data.can.manage_inventory, change: data.can.manage_inventory } }
  }
  const { data } = await api.get<Meta>('/products/meta/')
  return data
}

export async function uploadImage(productId: number, file: File, altText: string, isPrimary = false, scope: ProductScope = 'admin'): Promise<ProductImageRecord> {
  const form = new FormData()
  form.append('image', file)
  if (altText) form.append('alt_text', altText)
  if (isPrimary) form.append('is_primary', 'true')
  const { data } = await api.post<ProductImageRecord>(`${root(scope)}/${productId}/images/`, form)
  return data
}

export async function deleteImage(productId: number, imageId: number): Promise<void> {
  await api.delete(`/products/${productId}/images/${imageId}/`)
}

export async function setPrimaryImage(productId: number, imageId: number): Promise<ProductImageRecord> {
  const { data } = await api.post<ProductImageRecord>(`/products/${productId}/images/${imageId}/primary/`)
  return data
}

export interface SuggestionResult {
  available: boolean
  candidates: { url: string; source: string; license: string }[]
  reason?: string
}

export async function getImageSuggestions(productId: number): Promise<SuggestionResult> {
  const { data } = await api.get<SuggestionResult>(`/products/${productId}/image-suggestions/`)
  return data
}
