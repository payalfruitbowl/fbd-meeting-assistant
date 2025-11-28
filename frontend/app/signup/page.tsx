'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { signUp, isAuthenticated } from '../../lib/auth'
import Link from 'next/link'

export default function SignUpPage() {
  const router = useRouter()

  useEffect(() => {
    // Redirect to home if already authenticated
    if (isAuthenticated()) {
      router.push('/')
    }
  }, [router])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Validation
    if (password.length < 6) {
      setError('Password must be at least 6 characters')
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setLoading(true)
    try {
      await signUp(email, password)
      // Redirect to chat after successful signup
      router.push('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: '#0f172a',
      padding: '20px',
    }}>
      <div style={{
        width: '100%',
        maxWidth: '400px',
        backgroundColor: '#1e293b',
        borderRadius: '12px',
        padding: '32px',
        boxShadow: '0 10px 25px rgba(0, 0, 0, 0.3)',
      }}>
        <h1 style={{
          color: '#f1f5f9',
          fontSize: '28px',
          fontWeight: 'bold',
          marginBottom: '8px',
          textAlign: 'center',
        }}>
          Sign Up
        </h1>
        <p style={{
          color: '#94a3b8',
          fontSize: '14px',
          textAlign: 'center',
          marginBottom: '24px',
        }}>
          Create an account to start chatting
        </p>

        {error && (
          <div style={{
            backgroundColor: '#7f1d1d',
            color: '#fca5a5',
            padding: '12px',
            borderRadius: '8px',
            marginBottom: '20px',
            fontSize: '14px',
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '20px' }}>
            <label style={{
              display: 'block',
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500',
              marginBottom: '8px',
            }}>
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
                color: '#f1f5f9',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
              placeholder="your@email.com"
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{
              display: 'block',
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500',
              marginBottom: '8px',
            }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
                color: '#f1f5f9',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
              placeholder="At least 6 characters"
            />
          </div>

          <div style={{ marginBottom: '24px' }}>
            <label style={{
              display: 'block',
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500',
              marginBottom: '8px',
            }}>
              Confirm Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={6}
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
                color: '#f1f5f9',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
              placeholder="Confirm your password"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '12px',
              backgroundColor: loading ? '#475569' : '#3b82f6',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              fontSize: '16px',
              fontWeight: '600',
              cursor: loading ? 'not-allowed' : 'pointer',
              marginBottom: '16px',
            }}
          >
            {loading ? 'Signing up...' : 'Sign Up'}
          </button>
        </form>

        <p style={{
          color: '#94a3b8',
          fontSize: '14px',
          textAlign: 'center',
        }}>
          Already have an account?{' '}
          <Link href="/signin" style={{
            color: '#3b82f6',
            textDecoration: 'none',
            fontWeight: '500',
          }}>
            Sign In
          </Link>
        </p>
      </div>
    </div>
  )
}

