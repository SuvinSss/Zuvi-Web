import { Link } from 'react-router-dom'
import { Button } from '@/components/ui'

export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      <h1 className="text-2xl font-semibold text-forest">Page not found</h1>
      <p className="mt-2 text-sm text-muted">That page doesn’t exist or has moved.</p>
      <Link to="/"><Button className="mt-5">Go to home</Button></Link>
    </div>
  )
}
