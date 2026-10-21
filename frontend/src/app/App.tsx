import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { RouterProvider } from 'react-router-dom'
import { ToastProvider } from '@/components/kit'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { createRouter } from './router'

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: (count, error) => count < 1 && !(error as { response?: { status: number } }).response },
    },
  })
}

export function App() {
  const [client] = useState(makeClient)
  const [router] = useState(createRouter)
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
