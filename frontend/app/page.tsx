'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import ChatInterface from '../components/ChatInterface'
import { isAuthenticated } from '../components/auth'

export default function Home() {
  const router = useRouter()
  const [isClient, setIsClient] = useState(false)
  const [isAuth, setIsAuth] = useState(false)
  const [authChecked, setAuthChecked] = useState(false)

  useEffect(() => {
    setIsClient(true)

    // Only check auth once we're on client side
    if (typeof window !== 'undefined') {
      const auth = isAuthenticated()
      setIsAuth(auth)
      setAuthChecked(true)

      if (!auth) {
        router.push('/signin')
      }
    }
  }, [router])

  // Show loading while checking auth or if not authenticated
  if (!isClient || !authChecked || !isAuth) {
    return (
      <main style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-primary)',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{ color: 'var(--text-secondary)' }}>
          {!authChecked ? 'Checking authentication...' : 'Redirecting to sign in...'}
        </div>
      </main>
    )
  }

  return (
    <main style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: 'var(--bg-primary)',
    }}>
      <ChatInterface />
    </main>
  )
}

