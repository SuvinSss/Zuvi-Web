import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Lightbulb, Star, Trash2, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { errorMessage } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { deleteImage, getImageSuggestions, setPrimaryImage, uploadImage, type ProductScope } from '@/services/products'
import type { ProductDetail } from '@/types/api'
import { ProductImage } from './ProductImage'
import { Alert, Button, Card, Field, Input } from './ui'

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']

/** Pre-checks only for fast feedback; the server re-validates the actual file contents. */
export function checkImageFile(file: File): string | null {
  if (!ACCEPTED.includes(file.type)) return 'Choose a JPEG, PNG or WebP image.'
  if (file.size > MAX_UPLOAD_BYTES) return `That image is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`
  return null
}

export function ImageManager({ product, canChange, maxImages, scope = 'admin' }: { product: ProductDetail; canChange: boolean; maxImages: number; scope?: ProductScope }) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [alt, setAlt] = useState('')
  const [fileError, setFileError] = useState('')
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [showSuggestions, setShowSuggestions] = useState(false)
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['product', scope, product.id] }),
    queryClient.invalidateQueries({ queryKey: ['products'] }),
  ])
  const upload = useMutation({
    mutationFn: () => uploadImage(product.id, file as File, alt, product.images.length === 0, scope),
    onSuccess: async () => { setFile(null); setAlt(''); if (inputRef.current) inputRef.current.value = ''; await refresh() },
  })
  const remove = useMutation({ mutationFn: (id: number) => deleteImage(product.id, id), onSuccess: async () => { setConfirmId(null); await refresh() } })
  const primary = useMutation({ mutationFn: (id: number) => setPrimaryImage(product.id, id), onSuccess: refresh })
  const suggestions = useQuery({ queryKey: ['suggestions', product.id], queryFn: () => getImageSuggestions(product.id), enabled: showSuggestions, staleTime: Infinity })

  const full = product.images.length >= maxImages
  const mutationError = upload.error ?? remove.error ?? primary.error

  return (
    <Card className="p-4 sm:p-6">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-forest">Photos</h2>
          <p className="text-sm text-muted">Up to {maxImages}. Uploads are resized, cleaned of location data and compressed for fast loading.</p>
        </div>
        <span className="rounded-full bg-pale px-2.5 py-1 text-xs font-semibold text-deep">{product.images.length}/{maxImages}</span>
      </div>

      {mutationError && <div className="mb-4"><Alert tone="error">{errorMessage(mutationError)}</Alert></div>}
      {product.status === 'APPROVED' && canChange && scope === 'admin' && (
        <div className="mb-4"><Alert tone="warn">This product is approved. Adding or removing photos sends it back for re-approval.</Alert></div>
      )}

      {product.images.length === 0 ? (
        <div className="mb-4 grid grid-cols-[6rem_1fr] items-center gap-4 rounded-control bg-canvas p-3">
          <ProductImage image={product.image} name={product.name} />
          <p className="text-sm text-muted">No photo yet — customers see this placeholder until you upload one.</p>
        </div>
      ) : (
        <ul className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {product.images.map((image) => (
            <li key={image.id} className="space-y-2">
              <div className="relative">
                <ProductImage image={{ source: 'uploaded', alt_text: image.alt_text || product.name, thumbnail_url: image.thumbnail_url, display_url: image.display_url }} name={product.name} />
                {image.is_primary && (
                  <span className="absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded-full bg-forest px-2 py-0.5 text-[0.7rem] font-semibold text-white">
                    <Star className="size-3" aria-hidden="true" /> Primary
                  </span>
                )}
              </div>
              <p className="truncate text-xs text-muted" title={image.alt_text}>{image.width && image.height ? `${image.width}×${image.height} · ` : ''}{formatBytes(image.file_size)}</p>
              {canChange && scope === 'admin' && (confirmId === image.id ? (
                <div className="flex gap-1.5">
                  <Button variant="danger" className="min-h-9 flex-1 px-2 text-xs" loading={remove.isPending} onClick={() => remove.mutate(image.id)}>Confirm remove</Button>
                  <Button variant="ghost" className="min-h-9 px-2 text-xs" onClick={() => setConfirmId(null)}>Cancel</Button>
                </div>
              ) : (
                <div className="flex gap-1.5">
                  {!image.is_primary && <Button variant="secondary" className="min-h-9 flex-1 px-2 text-xs" loading={primary.isPending && primary.variables === image.id} onClick={() => primary.mutate(image.id)}>Make primary</Button>}
                  <Button variant="danger" className="min-h-9 px-2 text-xs" icon={Trash2} aria-label={`Remove photo ${image.id}`} onClick={() => setConfirmId(image.id)} />
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}

      {canChange && !full && (
        <form
          className="space-y-3 rounded-control border border-dashed border-line p-3 sm:p-4"
          onSubmit={(event) => { event.preventDefault(); if (file) upload.mutate() }}
        >
          <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
            <div className="aspect-square overflow-hidden rounded-control bg-canvas ring-1 ring-line">
              {preview ? <img src={preview} alt="Selected photo preview" className="size-full object-contain" /> : <div className="grid size-full place-items-center text-muted"><ImagePlus className="size-8" aria-hidden="true" /></div>}
            </div>
            <div className="space-y-3">
              <Field label="Choose a photo" error={fileError} hint="JPEG, PNG or WebP, up to 5 MB.">
                {(props) => (
                  <Input
                    {...props}
                    ref={inputRef}
                    type="file"
                    accept={ACCEPTED.join(',')}
                    className="file:mr-3 file:rounded-md file:border-0 file:bg-pale file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-forest"
                    onChange={(event) => {
                      const chosen = event.target.files?.[0] ?? null
                      const problem = chosen ? checkImageFile(chosen) : null
                      setFileError(problem ?? '')
                      setFile(problem ? null : chosen)
                    }}
                  />
                )}
              </Field>
              <Field label="Description (alt text)" hint="Helps screen readers and search. Optional.">
                {(props) => <Input {...props} maxLength={200} value={alt} onChange={(event) => setAlt(event.target.value)} />}
              </Field>
            </div>
          </div>
          <Button type="submit" icon={Upload} disabled={!file} loading={upload.isPending}>{upload.isPending ? 'Optimizing & uploading…' : 'Upload photo'}</Button>
        </form>
      )}
      {full && canChange && <p className="text-sm text-muted">Maximum number of photos reached. Remove one to add another.</p>}

      {scope === 'store' && <p className="mb-2 text-xs text-muted">To remove a photo or change the primary one, ask Zuuvi support.</p>}
      {scope === 'admin' && <div className="mt-4 border-t border-line pt-4">
        <Button variant="ghost" icon={Lightbulb} aria-expanded={showSuggestions} onClick={() => setShowSuggestions((value) => !value)}>Suggest photos</Button>
        {showSuggestions && (
          <div className="mt-2">
            {suggestions.isPending ? <p className="text-sm text-muted">Checking…</p>
              : suggestions.isError ? <Alert tone="error">Could not check for suggestions.</Alert>
              : suggestions.data.available ? <p className="text-sm">{suggestions.data.candidates.length} candidate(s) found. Review before applying.</p>
              : <Alert tone="info">{suggestions.data.reason ?? 'No suggestions available.'}</Alert>}
          </div>
        )}
      </div>}
    </Card>
  )
}
