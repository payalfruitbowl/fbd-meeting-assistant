'use client'

import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { queryAgentStream, deleteSession, type Message } from '@/lib/api'

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isHomePage, setIsHomePage] = useState(true)
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // Scroll to bottom when messages change (including during streaming)
  useEffect(() => {
    // Use setTimeout to ensure DOM is updated
    const timer = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: isLoading ? 'auto' : 'smooth' })
    }, 0)
    return () => clearTimeout(timer)
  }, [messages, isLoading])

  // Handle window close - cleanup session (ONLY on true tab/window close, NOT on refresh)
  useEffect(() => {
    if (!sessionId) return

    const handlePageHide = (e: PageTransitionEvent) => {
      // Only delete if page is being truly unloaded (not cached)
      if (e.persisted === false) {
        // Check if this navigation is a reload/refresh
        // If the page was loaded via reload, the navigation type will be 'reload'
        // We check this to avoid deleting on refresh
        const navEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
        const isReload = navEntry?.type === 'reload'
        
        // Only delete if it's NOT a reload (i.e., it's a close/navigation away)
        if (!isReload) {
          // Page is being closed (not refreshed), delete session
          // Use fetch with keepalive for reliable cleanup
          fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/agent/session/${sessionId}`, {
            method: 'DELETE',
            keepalive: true, // Ensures request completes even if page is unloading
          }).catch(() => {
            // Silently fail - page is unloading anyway
          })
        }
      }
    }

    window.addEventListener('pagehide', handlePageHide)

    return () => {
      window.removeEventListener('pagehide', handlePageHide)
    }
  }, [sessionId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    // Transition from home page to chat interface
    if (isHomePage) {
      setIsHomePage(false)
    }

    setMessages((prev) => [...prev, userMessage])
    const question = input.trim()
    setInput('')
    setIsLoading(true)

    // Add empty assistant message that will be updated with streaming
    const assistantMessageId = Date.now()
    setMessages((prev) => [...prev, {
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      id: assistantMessageId,
    }])

    try {
      await queryAgentStream(
        question,
        sessionId,
        (chunk: string) => {
          // Update the last message with streaming chunks
          setMessages((prev) => {
            const newMessages = [...prev]
            const lastMessage = newMessages[newMessages.length - 1]
            if (lastMessage && lastMessage.role === 'assistant') {
              return [...newMessages.slice(0, -1), {
                ...lastMessage,
                content: lastMessage.content + chunk
              }]
            }
            return newMessages
          })
        },
        (fullResponse: string, newSessionId: string) => {
          // Store session ID if this is the first message
          if (!sessionId && newSessionId) {
            setSessionId(newSessionId)
          }
          setIsLoading(false)
          inputRef.current?.focus()
        },
        (error: string) => {
          // Update last message with error
          setMessages((prev) => {
            const newMessages = [...prev]
            const lastMessage = newMessages[newMessages.length - 1]
            if (lastMessage && lastMessage.role === 'assistant') {
              lastMessage.content = `Error: ${error}`
            }
            return newMessages
          })
          setIsLoading(false)
          inputRef.current?.focus()
        }
      )
    } catch (error) {
      setMessages((prev) => {
        const newMessages = [...prev]
        const lastMessage = newMessages[newMessages.length - 1]
        if (lastMessage && lastMessage.role === 'assistant') {
          lastMessage.content = `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`
        }
        return newMessages
      })
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  if (isHomePage) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100vh',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 20px',
        position: 'relative',
      }}>
        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          style={{
            position: 'absolute',
            top: '24px',
            right: '24px',
            padding: '8px 16px',
            backgroundColor: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: '8px',
            color: 'var(--text-primary)',
            fontSize: '14px',
            cursor: 'pointer',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'
          }}
        >
          {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
        </button>

        {/* Centered Content */}
        <div className="home-content" style={{
          width: '100%',
          maxWidth: '80%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '32px',
        }}>
          <h1 style={{
            fontSize: '32px',
            fontWeight: '600',
            color: 'var(--text-primary)',
            margin: 0,
            textAlign: 'center',
            letterSpacing: '-0.5px',
          }}>
            Fruitbowl Assistant
          </h1>

          <p style={{
            fontSize: '16px',
            color: 'var(--text-secondary)',
            textAlign: 'center',
            margin: 0,
            lineHeight: '1.6',
          }}>
            Ask me about the Fruitbowl meetings and get detailed answers
          </p>

          <form
            onSubmit={handleSubmit}
            style={{
              width: '100%',
              display: 'flex',
              gap: '12px',
              alignItems: 'center',
            }}
          >
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about Fruitbowl meetings..."
              disabled={isLoading}
              style={{
                flex: 1,
                padding: '16px 20px',
                backgroundColor: 'var(--input-bg)',
                border: '1px solid var(--input-border)',
                borderRadius: '12px',
                fontSize: '16px',
                fontFamily: 'inherit',
                color: 'var(--text-primary)',
                outline: 'none',
                transition: 'all 0.2s ease',
              }}
              onFocus={(e) => {
                e.target.style.borderColor = 'var(--input-focus)'
                e.target.style.backgroundColor = 'var(--bg-tertiary)'
              }}
              onBlur={(e) => {
                e.target.style.borderColor = 'var(--input-border)'
                e.target.style.backgroundColor = 'var(--input-bg)'
              }}
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              style={{
                padding: '16px 32px',
                backgroundColor: input.trim() && !isLoading ? 'var(--accent-color)' : 'var(--bg-tertiary)',
              color: input.trim() && !isLoading 
                ? (theme === 'dark' ? '#1f1f1f' : '#ffffff')
                : 'var(--text-tertiary)',
                border: 'none',
                borderRadius: '12px',
                fontSize: '16px',
                fontWeight: '500',
                cursor: input.trim() && !isLoading ? 'pointer' : 'not-allowed',
                transition: 'all 0.2s ease',
                whiteSpace: 'nowrap',
              }}
              onMouseEnter={(e) => {
                if (input.trim() && !isLoading) {
                  e.currentTarget.style.backgroundColor = 'var(--accent-hover)'
                }
              }}
              onMouseLeave={(e) => {
                if (input.trim() && !isLoading) {
                  e.currentTarget.style.backgroundColor = 'var(--accent-color)'
                }
              }}
            >
              {isLoading ? '...' : 'Send'}
            </button>
          </form>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-container" style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      width: '100%',
      margin: 0,
      padding: 0,
    }}>
      {/* Header */}
      <header style={{
        padding: '12px 24px',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        backgroundColor: 'var(--bg-primary)',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}>
        <h1 style={{
          fontSize: '18px',
          fontWeight: '600',
          color: 'var(--text-primary)',
          margin: 0,
        }}>
          Fruitbowl Assistant
        </h1>
        <button
          onClick={toggleTheme}
          style={{
            padding: '6px 12px',
            backgroundColor: 'transparent',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            color: 'var(--text-primary)',
            fontSize: '13px',
            cursor: 'pointer',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent'
          }}
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </header>

      {/* Messages */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 0,
        display: 'flex',
        flexDirection: 'column',
      }}>
        {messages.map((message, index) => (
          <div
            key={message.id || index}
            style={{
              width: '100%',
              display: 'flex',
              flexDirection: 'column',
              borderBottom: '1px solid var(--border-color)',
              position: 'relative',
            }}
          >
            {/* Message Container */}
            <div style={{
              width: '100%',
              maxWidth: '100%',
              margin: '0 auto',
              padding: '24px 0',
            }}>
              <div style={{
                width: '100%',
                maxWidth: '1200px',
                margin: '0 auto',
                padding: '0 32px',
                display: 'flex',
                gap: '16px',
              }}>
                {/* Avatar/Icon */}
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '2px',
                  backgroundColor: message.role === 'user' ? 'var(--accent-color)' : 'var(--bg-tertiary)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  fontSize: '14px',
                  fontWeight: '600',
                  color: message.role === 'user' ? 'var(--bg-primary)' : 'var(--text-primary)',
                }}>
                  {message.role === 'user' ? 'U' : 'F'}
                </div>

                {/* Message Content */}
                <div style={{
                  flex: 1,
                  minWidth: 0,
                  color: 'var(--text-primary)',
                  fontSize: '16px',
                  lineHeight: '1.75',
                  wordBreak: 'break-word',
                  position: 'relative',
                }}>
                  {message.role === 'assistant' ? (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code: ({node, inline, ...props}: any) => {
                          if (inline) {
                            return (
                              <code style={{
                                backgroundColor: 'var(--bg-tertiary)',
                                padding: '2px 6px',
                                borderRadius: '3px',
                                fontSize: '0.9em',
                                fontFamily: 'monospace',
                              }} {...props} />
                            )
                          }
                          return <code {...props} />
                        },
                        pre: ({node, ...props}) => (
                          <pre style={{
                            backgroundColor: 'var(--bg-tertiary)',
                            padding: '12px',
                            borderRadius: '6px',
                            overflow: 'auto',
                            fontSize: '0.9em',
                            fontFamily: 'monospace',
                            border: '1px solid var(--border-color)',
                          }} {...props} />
                        ),
                        a: ({node, ...props}) => (
                          <a 
                            style={{ color: 'var(--accent-color)', textDecoration: 'underline' }}
                            target="_blank"
                            rel="noopener noreferrer"
                            {...props} 
                          />
                        ),
                      }}
                    >
                      {message.content}
                    </ReactMarkdown>
                  ) : (
                    <div style={{ 
                      whiteSpace: 'pre-wrap',
                      lineHeight: '1.75',
                      color: 'var(--text-primary)',
                    }}>
                      {message.content}
                    </div>
                  )}
                </div>
              </div>
              
              {/* Action Buttons Row - Only for assistant messages */}
              {message.role === 'assistant' && message.content && (
                <div style={{
                  width: '100%',
                  maxWidth: '1200px',
                  margin: '0 auto',
                  padding: '8px 32px 0 80px', // 80px = 32px avatar + 16px gap + 32px padding
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(message.content)
                        .then(() => {
                          // Show temporary feedback
                          const btn = document.getElementById(`copy-btn-${message.id || index}`)
                          if (btn) {
                            const originalHTML = btn.innerHTML
                            btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M13.5 4.5L6 12L2.5 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>'
                            setTimeout(() => {
                              if (btn) btn.innerHTML = originalHTML
                            }, 2000)
                          }
                        })
                        .catch(err => console.error('Failed to copy:', err))
                    }}
                    id={`copy-btn-${message.id || index}`}
                    style={{
                      padding: '6px',
                      backgroundColor: 'transparent',
                      border: 'none',
                      borderRadius: '4px',
                      color: 'var(--text-secondary)',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '28px',
                      height: '28px',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'
                      e.currentTarget.style.color = 'var(--text-primary)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = 'transparent'
                      e.currentTarget.style.color = 'var(--text-secondary)'
                    }}
                    title="Copy"
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M5.5 4.5V2.5C5.5 1.94772 5.94772 1.5 6.5 1.5H13.5C14.0523 1.5 14.5 1.94772 14.5 2.5V9.5C14.5 10.0523 14.0523 10.5 13.5 10.5H11.5M5.5 4.5H2.5C1.94772 4.5 1.5 4.94772 1.5 5.5V12.5C1.5 13.0523 1.94772 13.5 2.5 13.5H9.5C10.0523 13.5 10.5 13.0523 10.5 12.5V9.5M5.5 4.5C5.5 4.94772 5.94772 5.5 6.5 5.5H9.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div style={{
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            borderBottom: '1px solid var(--border-color)',
          }}>
            <div style={{
              width: '100%',
              maxWidth: '100%',
              margin: '0 auto',
              padding: '24px 0',
            }}>
              <div style={{
                width: '100%',
                maxWidth: '1200px',
                margin: '0 auto',
                padding: '0 32px',
                display: 'flex',
                gap: '16px',
              }}>
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '2px',
                  backgroundColor: 'var(--bg-tertiary)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  fontSize: '14px',
                  fontWeight: '600',
                  color: 'var(--text-primary)',
                }}>
                  F
                </div>
                <div style={{
                  flex: 1,
                  color: 'var(--text-secondary)',
                  fontSize: '16px',
                }}>
                  Thinking...
                </div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Form */}
      <form
        onSubmit={handleSubmit}
        style={{
          padding: '16px 0',
          borderTop: '1px solid var(--border-color)',
        }}
      >
        <div style={{
          width: '100%',
          maxWidth: '1200px',
          margin: '0 auto',
          padding: '0 32px',
          display: 'flex',
          gap: '12px',
          alignItems: 'flex-end',
        }}>
          <div style={{
            flex: 1,
            position: 'relative',
            display: 'flex',
            alignItems: 'flex-end',
            backgroundColor: 'var(--input-bg)',
            border: '1px solid var(--input-border)',
            borderRadius: '24px',
            padding: '12px 16px',
            transition: 'all 0.2s ease',
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = 'var(--input-focus)'
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = 'var(--input-border)'
          }}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Fruitbowl Assistant..."
              disabled={isLoading}
              style={{
                flex: 1,
                border: 'none',
                backgroundColor: 'transparent',
                fontSize: '16px',
                fontFamily: 'inherit',
                resize: 'none',
                minHeight: '24px',
                maxHeight: '200px',
                lineHeight: '1.5',
                color: 'var(--text-primary)',
                outline: 'none',
                padding: 0,
              }}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            style={{
              width: '32px',
              height: '32px',
              padding: 0,
              backgroundColor: input.trim() && !isLoading ? 'var(--accent-color)' : 'var(--bg-tertiary)',
              color: input.trim() && !isLoading 
                ? (theme === 'dark' ? '#1f1f1f' : '#ffffff')
                : 'var(--text-tertiary)',
              border: 'none',
              borderRadius: '50%',
              fontSize: '16px',
              cursor: input.trim() && !isLoading ? 'pointer' : 'not-allowed',
              transition: 'all 0.2s ease',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              if (input.trim() && !isLoading) {
                e.currentTarget.style.backgroundColor = 'var(--accent-hover)'
              }
            }}
            onMouseLeave={(e) => {
              if (input.trim() && !isLoading) {
                e.currentTarget.style.backgroundColor = 'var(--accent-color)'
              }
            }}
          >
            {isLoading ? '...' : '↑'}
          </button>
        </div>
      </form>
    </div>
  )
}

