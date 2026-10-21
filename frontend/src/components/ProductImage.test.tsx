import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CardImage } from '@/types/api'
import { ProductImage } from './ProductImage'

const uploaded: CardImage = {
  source: 'uploaded', alt_text: 'Red apples', thumbnail_url: '/media/t.webp', display_url: '/media/d.png', width: 400, height: 400,
}
const fallback: CardImage = {
  source: 'fallback', alt_text: '', thumbnail_url: null, display_url: null, fallback: { category: 'Fruit', category_slug: 'fruit', brand: '' },
}

describe('ProductImage', () => {
  it('shows the optimized thumbnail with alt text and reserved dimensions', () => {
    render(<ProductImage image={uploaded} name="Apples" />)
    const img = screen.getByRole('img', { name: 'Red apples' })
    expect(img).toHaveAttribute('src', '/media/t.webp')
    expect(img).toHaveAttribute('width', '400')
    expect(img).toHaveAttribute('loading', 'lazy')
  })

  it('uses the larger display image for the detail size', () => {
    render(<ProductImage image={uploaded} name="Apples" size="detail" />)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/media/d.png')
  })

  it('falls back to a placeholder when there is no image', () => {
    render(<ProductImage image={fallback} name="Mystery fruit" />)
    expect(screen.queryByRole('img', { name: 'Red apples' })).not.toBeInTheDocument()
    expect(document.querySelector('img[src="/media/t.webp"]')).toBeNull()
  })

  it('swaps to the placeholder if the image fails to load (never a broken image)', () => {
    const { container } = render(<ProductImage image={uploaded} name="Apples" />)
    fireEvent.error(screen.getByRole('img', { name: 'Red apples' }))
    expect(container.querySelector('img[src="/media/t.webp"]')).toBeNull()
    expect(container.firstChild).toBeTruthy()
  })

  it('handles a missing image object', () => {
    const { container } = render(<ProductImage image={null} name="No image" />)
    expect(container.firstChild).toBeTruthy()
  })
})
