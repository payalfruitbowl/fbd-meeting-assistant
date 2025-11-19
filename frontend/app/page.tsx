'use client'

import ChatInterface from '../components/ChatInterface'

export default function Home() {
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

