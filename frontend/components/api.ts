const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  id?: number
}

export interface AgentQueryRequest {
  question: string
  session_id?: string
}

export interface AgentQueryResponse {
  status: string
  response: string
  session_id: string
  message?: string
}

export async function queryAgentStream(
  question: string,
  sessionId: string | null,
  onChunk: (chunk: string) => void,
  onComplete: (fullResponse: string, newSessionId: string) => void,
  onError: (error: string) => void
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

