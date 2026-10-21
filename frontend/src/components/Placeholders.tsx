import { Baby, CupSoda, Droplets, Milk, Package, ShoppingBasket, Sparkles, Cookie, type LucideIcon } from 'lucide-react'

interface Kind {
  key: string
  label: string
  Icon: LucideIcon
  words: string[]
}

/** Bundled, offline category placeholders. They are illustrations, never photographs. */
const KINDS: Kind[] = [
  { key: 'dairy', label: 'Dairy', Icon: Milk, words: ['dairy', 'milk', 'curd', 'cheese', 'butter', 'egg'] },
  { key: 'beverages', label: 'Beverages', Icon: CupSoda, words: ['beverage', 'drink', 'juice', 'tea', 'coffee', 'water', 'soda'] },
  { key: 'snacks', label: 'Snacks', Icon: Cookie, words: ['snack', 'biscuit', 'chocolate', 'sweet', 'bakery', 'chips'] },
  { key: 'household', label: 'Household', Icon: Droplets, words: ['household', 'clean', 'detergent', 'kitchen', 'home'] },
  { key: 'personal-care', label: 'Personal care', Icon: Sparkles, words: ['personal', 'beauty', 'soap', 'care', 'hair', 'skin'] },
  { key: 'baby', label: 'Baby', Icon: Baby, words: ['baby', 'kid', 'infant'] },
  { key: 'grocery', label: 'Grocery', Icon: ShoppingBasket, words: ['grocer', 'rice', 'dal', 'flour', 'oil', 'spice', 'vegetable', 'fruit', 'staple', 'atta'] },
]
const GENERIC: Kind = { key: 'generic', label: 'Product', Icon: Package, words: [] }

export function placeholderKind(category = '', slug = ''): Kind {
  const haystack = `${category} ${slug}`.toLowerCase()
  return KINDS.find((kind) => kind.words.some((word) => haystack.includes(word))) ?? GENERIC
}

export function Placeholder({ category, slug, name, compact = false }: { category?: string; slug?: string; name: string; compact?: boolean }) {
  const { Icon, label, key } = placeholderKind(category, slug)
  return (
    <div
      role="img"
      aria-label={`${name} — no photo yet (${label} placeholder)`}
      data-placeholder={key}
      className="flex h-full w-full flex-col items-center justify-center gap-1 bg-gradient-to-br from-pale to-mint text-deep"
    >
      <Icon className={compact ? 'size-1/2' : 'size-2/5'} strokeWidth={1.4} aria-hidden="true" />
      {!compact && <span className="text-[0.65rem] font-medium uppercase tracking-wider text-forest/70">{label} · placeholder</span>}
    </div>
  )
}
