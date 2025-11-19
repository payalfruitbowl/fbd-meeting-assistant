# Meeting Transcript Assistant - Frontend

Minimalistic Next.js frontend for the RAG-based meeting transcript assistant.

## Features

- Clean, minimal design (no gradients, simple colors)
- Chat interface similar to ChatGPT/Perplexity
- Session-based conversations
- Automatic session cleanup on window/tab close
- No permanent storage - temporary sessions only

## Setup

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Configure backend URL:**
   Create `.env.local` file:
   ```
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

3. **Run development server:**
   ```bash
   npm run dev
   ```

4. **Open in browser:**
   Navigate to `http://localhost:3000`

## Build for Production

```bash
npm run build
npm start
```

## Session Management

- Sessions are automatically created on first query
- Session ID is maintained throughout the conversation
- Session is automatically deleted when:
  - User closes the tab/window
  - User navigates away
  - Component unmounts

No conversation history is stored permanently.




