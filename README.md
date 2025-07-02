# Gemini Coding Assistant MCP Server

A powerful MCP server that allows Claude Code to consult Gemini for complex coding problems with full code context and conversation persistence.

## Key Features

- **Session Management**: Maintain conversation context across multiple queries
- **File Attachments**: Read and include actual code files in conversations
- **Hybrid Context**: Combine text-based `code_context` with file attachments
- **Follow-up Questions**: Ask follow-up questions without resending code context
- **Context Caching**: Code context and file content are cached per session
- **Automatic Processing**: Files are processed and formatted automatically
- **Multiple Sessions**: Run multiple parallel conversations for different problems
- **Session Expiry**: Automatic cleanup of inactive sessions after 1 hour
- **Latest Model**: Uses Gemini 2.5 Pro (stable) by default

## Purpose

When Claude Code encounters difficult problems or needs a second opinion, it can:
- Send complete code files by reading them from the local filesystem
- Include text-based code context alongside file attachments
- Have multi-turn conversations about the same problem
- Get different perspectives without repeating context
- Work on multiple problems in parallel sessions
- Process files locally and include content in conversations

## Installation

1. Clone this repository
2. Create a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and add your Gemini API key:
   ```bash
   cp .env.example .env
   # Edit .env file and set your GEMINI_API_KEY
   ```
5. Add to Claude Code:
   ```bash
   claude mcp add gemini-coding -s user -- /path/to/gemini-mcp/start_server.sh
   ```
   Replace `/path/to/gemini-mcp/` with the actual path to this directory.

## Tools Available

### 1. `consult_gemini`
Start or continue a conversation with Gemini about complex coding problems.

**Parameters:**
- `session_id` (optional): Continue a previous conversation
- `problem_description`: Description of the problem (required for new sessions)
- `code_context`: All relevant code (required for new sessions, cached afterward)
- `attached_files` (optional): Array of file paths to read and include in the conversation
- `file_descriptions` (optional): Object mapping file paths to descriptions
- `specific_question`: The question you want answered
- `additional_context` (optional): Updates or changes since last question
- `preferred_approach`: Type of help needed (solution/review/debug/optimize/explain/follow-up)

### 2. `list_sessions`
List all active Gemini consultation sessions.

### 3. `end_session`
End a specific session to free up memory.

## Usage Examples

### Starting a New Conversation (with text code)
```
/consult_gemini 
  problem_description: "I need to implement efficient caching for a React application"
  code_context: "[paste entire relevant codebase]"
  specific_question: "What's the best approach for implementing LRU cache with React Query?"
  preferred_approach: "solution"
```

### Starting a New Conversation (with file attachments)
```
/consult_gemini 
  problem_description: "I need to optimize this React component for performance"
  attached_files: ["/absolute/path/to/src/components/Dashboard.jsx", "/absolute/path/to/src/hooks/useData.js", "/absolute/path/to/package.json"]
  file_descriptions: {
    "/absolute/path/to/src/components/Dashboard.jsx": "Main dashboard component with performance issues",
    "/absolute/path/to/src/hooks/useData.js": "Custom hook for data fetching", 
    "/absolute/path/to/package.json": "Project dependencies"
  }
  specific_question: "How can I improve the rendering performance of this dashboard?"
  preferred_approach: "optimize"
```

### Combining Both Approaches
```
/consult_gemini 
  problem_description: "Complex authentication flow needs debugging"
  code_context: "// Additional context or pseudocode here"
  attached_files: ["/absolute/path/to/auth/login.js", "/absolute/path/to/middleware/auth.js"]
  specific_question: "Why is the token refresh failing?"
  preferred_approach: "debug"
```

Response includes a session ID for follow-ups.

### Follow-up Question
```
/consult_gemini
  session_id: "abc123..."
  specific_question: "I implemented your suggestion but getting stale data issues. How do I handle cache invalidation?"
  additional_context: "Added the LRU cache as suggested, but users see old data after updates"
  preferred_approach: "follow-up"
```

### Managing Sessions
```
/list_sessions
# Shows all active sessions with IDs and summaries

/end_session
  session_id: "abc123..."
# Frees up memory for completed conversations
```

## Best Practices

1. **Initial Context**: Include ALL relevant code via `code_context` or `attached_files`
2. **File Organization**: Use `attached_files` for multiple files, `code_context` for snippets
3. **File Descriptions**: Provide clear descriptions for each attached file
4. **Follow-ups**: Use the session ID to continue conversations
5. **Additional Context**: When asking follow-ups, explain what changed
6. **Session Management**: End sessions when done to free memory and clean up files
7. **Multiple Problems**: Use different sessions for unrelated problems
8. **File Types**: Supports JavaScript, Python, TypeScript, JSON, and other text-based files

## Testing the Server

You can test the server directly before adding it to Claude Code:

```bash
# Make sure your .env file has a valid GEMINI_API_KEY
./start_server.sh
```

The server will start and display:
```
Gemini Coding Assistant MCP Server v3.0 running (Python)
Features: Session management, file attachments, context persistence, follow-up questions
Ready to help with complex coding problems!
```

## Context Limits

- Maximum combined input: ~50,000 characters per message
- Maximum response: 8,192 tokens (~16,000 characters)
- Session timeout: 1 hour of inactivity
- Rate limiting: 1 second between requests

## How It Works

1. **First Message**: Creates a new session, caches code context
2. **Follow-ups**: Reuses cached context, maintains conversation history
3. **Session Storage**: In-memory storage (use Redis for production)
4. **Cleanup**: Automatic expiry after 1 hour of inactivity

## Advantages Over Stateless Design

- **Efficiency**: Code context sent only once per session
- **Context**: Gemini remembers previous questions and answers
- **Natural Flow**: Have real conversations about complex problems
- **Cost Savings**: Reduced token usage for follow-up questions

## Security

- API key is never exposed
- Rate limiting prevents abuse
- Sessions expire automatically
- No persistent storage of code

## Version History

- v2.1.0: Added file attachment system with automatic cleanup
- v2.0.0: Added session management and follow-up support  
- v1.0.0: Initial stateless implementation