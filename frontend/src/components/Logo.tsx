import darkLogo from '@/assets/brand/zuvi-logo-dark.png'
import lightLogo from '@/assets/brand/zuvi-logo-light.png'
import darkMark from '@/assets/brand/zuvi-mark-dark.png'
import lightMark from '@/assets/brand/zuvi-mark-light.png'

/**
 * The official Zuvi wordmark. Assets are cut from the supplied brand reference
 * and never restyled: width/height keep the original proportions (722×240) and
 * the CSS only ever sets one dimension.
 *  - variant "light": for light surfaces (white / pale green)
 *  - variant "dark":  for the deep-green surfaces (#081F1D)
 */
export function Logo({ variant = 'light', mark = false, className = '' }: { variant?: 'light' | 'dark'; mark?: boolean; className?: string }) {
  const src = mark ? (variant === 'dark' ? darkMark : lightMark) : variant === 'dark' ? darkLogo : lightLogo
  const [width, height] = mark ? [251, 240] : [722, 240]
  return <img src={src} width={width} height={height} alt="Zuvi" className={`h-auto select-none ${className}`} draggable={false} />
}
