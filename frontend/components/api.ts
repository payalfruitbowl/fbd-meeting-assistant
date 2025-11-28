const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  id?: string | number
}

export interface AgentQueryRequest {
  question: string
  session_id?: string
  conversation_id?: string
}

export interface AgentQueryResponse {
  status: string
  response: string
  session_id: string
  message?: string
}

// Conversation interfaces
export interface Conversation {
  id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface CreateConversationRequest {
  title?: string
}

export interface UpdateConversationTitleRequest {
  title: string
}

// Message interfaces
export interface ConversationMessage {
  id: string
  conversation_id: string
  role: string
  content: string
  created_at: string
}

export interface AddMessageRequest {
  conversation_id: string
  role: string
  content: string
}

export async function queryAgentStream(
  question: string,
  sessionId: string | null,
  onChunk: (chunk: string) => void,
  onComplete: (fullResponse: string, newSessionId: string) => void,
  onError: (error: string) => void,
  conversationId?: string
): Promise<void> {
  try {
    const response = await fetch(`${API_URL}/agent/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question,
        session_id: sessionId || undefined,
        conversation_id: conversationId || undefined,
      }),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
      onError(error.detail || `HTTP error! status: ${response.status}`)
      return
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullResponse = ''
    let currentSessionId = sessionId

    if (!reader) {
      onError('No response body')
      return
    }

    while (true) {
      const { done, value } = await reader.read()
      
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            
            if (data.type === 'session') {
              currentSessionId = data.session_id
            } else if (data.type === 'chunk') {
              fullResponse += data.content
              onChunk(data.content)
            } else if (data.type === 'done') {
              onComplete(data.response || fullResponse, data.session_id || currentSessionId || '')
              return
            } else if (data.type === 'error') {
              onError(data.error || 'Unknown error')
              return
            }
          } catch (e) {
            console.error('Error parsing SSE data:', e)
          }
        }
      }
    }
  } catch (error) {
    onError(error instanceof Error ? error.message : 'Network error')
  }
}

export async function deleteSession(sessionId: string): Promise<void> {
  try {
    const response = await fetch(`${API_URL}/agent/session/${sessionId}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      console.error('Failed to delete session:', response.status)
    }
  } catch (error) {
    console.error('Failed to delete session:', error)
  }
}

// Conversation API functions
export async function createConversation(title?: string): Promise<Conversation> {
  const response = await fetch(`${API_URL}/conversations`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ title }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to create conversation' }))
    throw new Error(error.detail || 'Failed to create conversation')
  }

  return response.json()
}

export async function getConversations(limit = 50): Promise<Conversation[]> {
  const response = await fetch(`${API_URL}/conversations?limit=${limit}`, {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch conversations' }))
    throw new Error(error.detail || 'Failed to fetch conversations')
  }

  return response.json()
}

export async function getConversation(conversationId: string): Promise<Conversation> {
  const response = await fetch(`${API_URL}/conversations/${conversationId}`, {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch conversation' }))
    throw new Error(error.detail || 'Failed to fetch conversation')
  }

  return response.json()
}

export async function updateConversationTitle(conversationId: string, title: string): Promise<Conversation> {
  const response = await fetch(`${API_URL}/conversations/${conversationId}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify({ title }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to update conversation' }))
    throw new Error(error.detail || 'Failed to update conversation')
  }

  return response.json()
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`${API_URL}/conversations/${conversationId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to delete conversation' }))
    throw new Error(error.detail || 'Failed to delete conversation')
  }
}

// Message API functions
export async function addMessage(conversationId: string, role: string, content: string): Promise<ConversationMessage> {
  const response = await fetch(`${API_URL}/messages`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      conversation_id: conversationId,
      role,
      content,
    }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to add message' }))
    throw new Error(error.detail || 'Failed to add message')
  }

  return response.json()
}

export async function getConversationMessages(conversationId: string, limit = 100): Promise<ConversationMessage[]> {
  const response = await fetch(`${API_URL}/conversations/${conversationId}/messages?limit=${limit}`, {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch messages' }))
    throw new Error(error.detail || 'Failed to fetch messages')
  }

  return response.json()
}

// Helper function to get auth headers
function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }

  // Import getAccessToken dynamically to avoid circular imports
  const token = typeof window !== 'undefined' ? localStorage.getItem('supabase_access_token') : null
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return headers
}

