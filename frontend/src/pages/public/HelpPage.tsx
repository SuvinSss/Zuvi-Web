import { LifeBuoy, MessageSquareWarning, MessagesSquare, Truck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, PageHeader } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'

const topics = [
  { to: '/account/support/new-ticket', icon: LifeBuoy, title: 'Get help with an order', text: 'Open a support ticket about an order, payment, delivery or your account.' },
  { to: '/account/support/new-complaint', icon: MessageSquareWarning, title: 'Make a complaint', text: 'Formally report a problem with a store, product or delivery partner, with photo evidence.' },
  { to: '/account/feedback', icon: MessagesSquare, title: 'Send feedback', text: 'Suggestions, praise or questions about Zuvi. This is not a complaint.' },
  { to: '/account/orders', icon: Truck, title: 'Track my order', text: 'See where your order is and who is delivering it.' },
]

export default function HelpPage() {
  const { user } = useAuth()
  return (
    <>
      <PageHeader title="Help & support" subtitle="Choose what you need. You need to be signed in as a customer to contact support." />
      <div className="grid gap-3 sm:grid-cols-2">
        {topics.map(({ to, icon: Icon, title, text }) => (
          <Link key={to} to={user ? to : '/login'} state={user ? undefined : { from: to }}>
            <Card className="flex h-full gap-3 p-4 hover:border-emerald/50"><Icon className="mt-0.5 size-6 shrink-0 text-emerald" aria-hidden="true" /><div><h2 className="font-semibold text-forest">{title}</h2><p className="mt-0.5 text-sm text-muted">{text}</p></div></Card>
          </Link>
        ))}
      </div>
    </>
  )
}
