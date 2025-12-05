'use client'

import { useEffect, useState, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import ChatInterface from '../components/ChatInterface'
import { isAuthenticated } from '../components/auth'

export default function Home() {
  const router = useRouter()
  const pathname = usePathname()
  const [isClient, setIsClient] = useState(false)
  const [isAuth, setIsAuth] = useState(false)
  const [authChecked, setAuthChecked] = useState(false)
  const redirectAttempted = useRef(false) // Prevent multiple redirects

  useEffect(() => {
    setIsClient(true)

    // Only check auth once we're on client side
    if (typeof window !== 'undefined' && !redirectAttempted.current) {
      const auth = isAuthenticated()
      setIsAuth(auth)
      setAuthChecked(true)

      // Only redirect if not authenticated AND we're actually on home page
      // Use replace instead of push to avoid history stack issues
      if (!auth && pathname === '/') {
        redirectAttempted.current = true
        router.replace('/signin')
      }
    }
  }, [router, pathname])

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

