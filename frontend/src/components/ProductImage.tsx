import { useState } from 'react'
import type { CardImage } from '@/types/api'
import { Placeholder } from './Placeholders'

interface Props {
  image: CardImage | null | undefined
  name: string
  /** thumb = grids and lists (small WebP); detail = larger display image */
  size?: 'thumb' | 'detail'
  eager?: boolean
  className?: string
}

/**
 * Always renders something sensible: the optimized image if it loads, otherwise
 * a bundled placeholder — never a broken-image icon. The box is square and
 * reserved up front (no layout shift); images are *contained* on a neutral
 * background so product details are never cropped away.
 */
export function ProductImage({ image, name, size = 'thumb', eager = false, className = '' }: Props) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const url = image ? (size === 'detail' ? (image.display_url ?? image.thumbnail_url) : image.thumbnail_url) : null
  const showImage = Boolean(url) && failedUrl !== url
  return (
    <div className={`relative aspect-square overflow-hidden rounded-control bg-canvas ring-1 ring-line ${className}`}>
      {showImage && url ? (
        <img
          src={url}
          alt={image?.alt_text || name}
          width={image?.width ?? 400}
          height={image?.height ?? 400}
          loading={eager ? 'eager' : 'lazy'}
          decoding="async"
          onError={() => setFailedUrl(url)}
          className="size-full object-contain"
        />
      ) : (
        <Placeholder category={image?.fallback?.category} slug={image?.fallback?.category_slug} name={name} compact={size === 'thumb'} />
      )}
    </div>
  )
}
