const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface AuthResponse {
  status: string
  user?: {
    id: string
    email: string
  }
  session?: {
    access_token: string
    refresh_token: string
  }
  message?: string
}

export interface User {
  id: string
  email: string
}

// Token storage keys
const ACCESS_TOKEN_KEY = 'supabase_access_token'
const USER_KEY = 'supabase_user'

// Auth API functions
export async function signUp(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_URL}/auth/signup`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Sign up failed' }))
    throw new Error(error.detail || 'Sign up failed')
  }

  const data: AuthResponse = await response.json()
  
  // Store token and user
  if (data.session?.access_token) {
    localStorage.setItem(ACCESS_TOKEN_KEY, data.session.access_token)
  }
  if (data.user) {
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  }

  return data
}

export async function signIn(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_URL}/auth/signin`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Sign in failed' }))
    throw new Error(error.detail || 'Invalid email or password')
  }

  const data: AuthResponse = await response.json()
  
  // Store token and user
  if (data.session?.access_token) {
    localStorage.setItem(ACCESS_TOKEN_KEY, data.session.access_token)
  }
  if (data.user) {
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  }

  return data
}

export function signOut(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getCurrentUser(): User | null {
  if (typeof window === 'undefined') return null
  const userStr = localStorage.getItem(USER_KEY)
  if (!userStr) return null
  try {
    return JSON.parse(userStr)
  } catch {
    return null
  }
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null
}

// Get auth headers for API requests
export function getAuthHeaders(): HeadersInit {
  const token = getAccessToken()
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}






