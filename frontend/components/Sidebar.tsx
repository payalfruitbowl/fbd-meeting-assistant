'use client'

import { useState, useEffect } from 'react'
import { getConversations, Conversation, deleteConversation } from './api'
import { signOut } from '../lib/auth'

interface SidebarProps {
  currentConversationId?: string
  onConversationSelect: (conversationId: string) => void
  onNewChat: () => void
  isCollapsed?: boolean
  onToggleCollapse?: () => void
  refreshTrigger?: number
}

export default function Sidebar({ currentConversationId, onConversationSelect, onNewChat, isCollapsed = false, onToggleCollapse, refreshTrigger }: SidebarProps) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState<string | null>(null)

  // Load conversations on component mount and when refresh is triggered
  useEffect(() => {
    loadConversations()
  }, [refreshTrigger])

  // Handle click outside to close menu
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuOpen) {
        const target = event.target as Element
        // Check if the click is outside the menu
        if (!target.closest('[data-menu-container]')) {
          setMenuOpen(null)
        }
      }
    }

    const handleEscapeKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && menuOpen) {
        setMenuOpen(null)
      }
    }

    if (menuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('keydown', handleEscapeKey)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscapeKey)
    }
  }, [menuOpen])

  const loadConversations = async () => {
    try {
      setIsLoading(true)
      setError(null)
      const convs = await getConversations(50)
      setConversations(convs)
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load conversations'
      console.error('Failed to load conversations:', err)

      // If authentication fails, redirect to sign-in immediately
      if (errorMessage.includes('401') || errorMessage.includes('Unauthorized') || errorMessage.includes('Invalid or expired token') || errorMessage.includes('Token')) {
        window.location.href = '/signin'
        return
      } else {
        setError(errorMessage)
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleNewChat = () => {
    // Navigate to home page for new chat input
    // Don't create conversation here - let the home page handle it
    window.location.href = '/'
  }

  const handleSignOut = () => {
    signOut()
    window.location.href = '/signin'
  }

  const handleDeleteConversation = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent triggering conversation selection

    if (!confirm('Are you sure you want to delete this conversation?')) {
      return
    }

    try {
      await deleteConversation(conversationId)
      setConversations(prev => prev.filter(conv => conv.id !== conversationId))

      // If the deleted conversation was currently selected, start a new chat
      if (currentConversationId === conversationId) {
        onNewChat()
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err)
      alert('Failed to delete conversation')
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) {
      return 'Today'
    } else if (diffDays === 1) {
      return 'Yesterday'
    } else if (diffDays < 7) {
      return `${diffDays} days ago`
    } else {
      return date.toLocaleDateString()
    }
  }

  return (
    <div style={{
      width: isCollapsed ? '60px' : '280px',
      height: '100vh',
      backgroundColor: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      position: 'fixed',
      left: 0,
      top: 0,
      zIndex: 100,
      transition: 'width 0.3s ease',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
      }}>
        {/* Toggle button only */}
        <div style={{
          display: 'flex',
          justifyContent: 'flex-start',
          alignItems: 'center',
        }}>
          <button
            onClick={onToggleCollapse}
            style={{
              padding: '6px',
              backgroundColor: 'transparent',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)'
              e.currentTarget.style.color = 'var(--text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--text-secondary)'
            }}
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              {isCollapsed ? (
                <path d="M9 5L15 12L9 19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              ) : (
                <path d="M15 5L9 12L15 19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              )}
            </svg>
          </button>
        </div>

        {/* New Chat button - hide when collapsed */}
        {!isCollapsed && (
          <button
            onClick={handleNewChat}
            style={{
              width: '100%',
              padding: '12px 16px',
              backgroundColor: 'var(--accent-color)',
              color: 'var(--bg-primary)',
              border: 'none',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--accent-hover)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--accent-color)'
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 4V20M4 12H20" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            New Chat
          </button>
        )}
      </div>

      {/* CHATS Section */}
      {!isCollapsed && (
        <div style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{
            padding: '16px',
            borderBottom: '1px solid var(--border-color)',
            backgroundColor: 'var(--bg-primary)',
          }}>
            <h3 style={{
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--text-secondary)',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
              margin: 0,
            }}>
              CHATS
            </h3>
          </div>

        {/* Conversations List */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 0',
        }}>
          {isLoading ? (
            <div style={{
              padding: '16px',
              textAlign: 'center',
              color: 'var(--text-secondary)',
              fontSize: '14px',
            }}>
              Loading conversations...
            </div>
          ) : error ? (
            <div style={{
              padding: '16px',
              textAlign: 'center',
              color: 'var(--text-error)',
              fontSize: '14px',
            }}>
              {error}
              <button
                onClick={loadConversations}
                style={{
                  display: 'block',
                  margin: '8px auto 0',
                  padding: '4px 8px',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-color)',
                  borderRadius: '4px',
                  color: 'var(--text-secondary)',
                  fontSize: '12px',
                  cursor: 'pointer',
                }}
              >
                Retry
              </button>
            </div>
          ) : conversations.length === 0 ? (
            <div style={{
              padding: '32px 16px',
              textAlign: 'center',
              color: 'var(--text-secondary)',
              fontSize: '14px',
            }}>
              No conversations yet.<br/>
              Start a new chat above!
            </div>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.id}
                onClick={() => onConversationSelect(conversation.id)}
                style={{
                  padding: '12px 16px',
                  cursor: 'pointer',
                  backgroundColor: currentConversationId === conversation.id
                    ? 'var(--bg-tertiary)'
                    : 'transparent',
                  border: 'none',
                  borderRadius: '0',
                  textAlign: 'left',
                  transition: 'background-color 0.2s ease',
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
                onMouseEnter={(e) => {
                  if (currentConversationId !== conversation.id) {
                    e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (currentConversationId !== conversation.id) {
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: '14px',
                    fontWeight: '500',
                    color: 'var(--text-primary)',
                    marginBottom: '2px',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                    {conversation.title || 'Untitled Chat'}
                  </div>
                  <div style={{
                    fontSize: '12px',
                    color: 'var(--text-secondary)',
                  }}>
                    {formatDate(conversation.updated_at)}
                  </div>
                </div>

                {/* Three dots menu button */}
                <div style={{ position: 'relative' }} data-menu-container>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setMenuOpen(menuOpen === conversation.id ? null : conversation.id)
                    }}
                    style={{
                      padding: '4px',
                      backgroundColor: 'transparent',
                      border: 'none',
                      borderRadius: '4px',
                      color: 'var(--text-secondary)',
                      cursor: 'pointer',
                      opacity: 1,
                      transition: 'all 0.2s ease',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '24px',
                      height: '24px',
                    }}
                    title="More options"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
                      <circle cx="19" cy="12" r="1.5" fill="currentColor"/>
                      <circle cx="5" cy="12" r="1.5" fill="currentColor"/>
                    </svg>
                  </button>

                  {/* Dropdown menu */}
                  {menuOpen === conversation.id && (
                    <div
                      style={{
                        position: 'absolute',
                        right: '0',
                        top: '100%',
                        backgroundColor: 'var(--bg-primary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '8px',
                        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
                        zIndex: 1000,
                        minWidth: '120px',
                        padding: '4px 0',
                      }}
                    >
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDeleteConversation(conversation.id, e)
                          setMenuOpen(null)
                        }}
                        style={{
                          width: '100%',
                          padding: '8px 16px',
                          backgroundColor: 'transparent',
                          border: 'none',
                          color: 'var(--text-error)',
                          fontSize: '14px',
                          cursor: 'pointer',
                          textAlign: 'left',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          transition: 'background-color 0.2s ease',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)'
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = 'transparent'
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <path d="M19 7L5 21M5 7L19 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          </div>
        </div>
      )}

      {/* Sign Out Button - Fixed at bottom (only when expanded) */}
      {!isCollapsed && (
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          padding: '16px',
          borderTop: '1px solid var(--border-color)',
          backgroundColor: 'var(--bg-primary)',
        }}>
          <button
            onClick={handleSignOut}
            style={{
              width: '100%',
              padding: '12px 16px',
              backgroundColor: 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)'
              e.currentTarget.style.borderColor = 'var(--accent-color)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'
              e.currentTarget.style.borderColor = 'var(--border-color)'
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M9 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M16 17L21 12L16 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M21 12H9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Sign Out
          </button>
        </div>
      )}
    </div>
  )
}
