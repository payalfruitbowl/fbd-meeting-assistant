'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import ChatInterface from '../components/ChatInterface'
import { isAuthenticated } from '@/lib/auth'

export default function Home() {
  const router = useRouter()
  const [isClient, setIsClient] = useState(false)
  const [isAuth, setIsAuth] = useState(false)

  useEffect(() => {
    setIsClient(true)
    const auth = isAuthenticated()
    setIsAuth(auth)
    
    if (!auth) {
      router.push('/signin')
    }
  }, [router])

  // Show nothing while checking auth (prevents flash and hydration errors)
  if (!isClient || !isAuth) {
    return (
      <main style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-primary)',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{ color: 'var(--text-secondary)' }}>Loading...</div>
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

