#!/usr/bin/env python3

import asyncio
import os
import sys
import time
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

from google import genai
from google.genai import types
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
import json

# Configure environment
if not os.getenv('GEMINI_API_KEY'):
    print("Error: GEMINI_API_KEY environment variable is required", file=sys.stderr)
    sys.exit(1)

# Initialize client
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# Configuration
MODEL_NAME = os.getenv('GEMINI_MODEL', 'gemini-2.5-pro')
SESSION_TTL = 3600  # 1 hour in seconds

# Default system prompt for Gemini
DEFAULT_SYSTEM_PROMPT = """You are an expert coding assistant helping Claude (another AI) solve complex programming problems. 

Your role:
- Provide clear, practical solutions with working code examples
- Explain your reasoning concisely but thoroughly
- Focus on best practices, security, and maintainability
- Suggest optimizations when relevant
- Point out potential issues or edge cases
- Use the specific technologies and frameworks shown in the provided code context

Response guidelines:
- Start with a brief summary of your approach
- Provide complete, runnable code examples when possible
- Explain key concepts or non-obvious implementations
- Suggest testing strategies when appropriate
- Be direct and actionable - Claude needs specific guidance to help the user
- If you need additional context to provide a solid answer, ask Claude specific clarifying questions about:
  - Requirements or constraints not mentioned
  - Preferred approaches or technologies
  - Error messages or specific behaviors
  - Environment details or deployment context
  - Performance requirements or scale considerations

Remember: You're consulting with another AI to help a human developer, so be precise and comprehensive in your technical advice."""

SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT', DEFAULT_SYSTEM_PROMPT)

@dataclass
class ProcessedFile:
    """Information about a processed file."""
    file_type: str
    file_uri: str
    mime_type: str
    file_name: str
    file_path: str
    gemini_file_id: str

@dataclass
class Session:
    """Chat session with Gemini."""
    session_id: str
    chat: Any
    created: datetime
    last_used: datetime
    message_count: int
    problem_description: Optional[str] = None
    code_context: Optional[str] = None
    processed_files: Dict[str, ProcessedFile] = None
    
    def __post_init__(self):
        if self.processed_files is None:
            self.processed_files = {}

class GeminiMCPServer:
    """MCP Server for Gemini file attachment functionality."""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.last_request_time = 0
        self.min_time_between_requests = 1.0  # 1 second
        self._cleanup_task = None
    
    def _ensure_cleanup_task_started(self):
        """Start cleanup task if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_sessions())
    
    async def _cleanup_sessions(self):
        """Periodically clean up expired sessions."""
        while True:
            await asyncio.sleep(300)  # Check every 5 minutes
            now = datetime.now()
            expired_sessions = []
            
            for session_id, session in self.sessions.items():
                if (now - session.last_used).total_seconds() > SESSION_TTL:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                await self._cleanup_session_files(session_id)
                del self.sessions[session_id]
                print(f"[{datetime.now().isoformat()}] Session {session_id} expired and removed", file=sys.stderr)
    
    async def _cleanup_session_files(self, session_id: str):
        """Clean up uploaded files for a session."""
        if session_id not in self.sessions:
            return
            
        session = self.sessions[session_id]
        for file_path, file_info in session.processed_files.items():
            try:
                client.files.delete(file_info.gemini_file_id)
                print(f"[{datetime.now().isoformat()}] Session {session_id}: Deleted file {file_info.file_name}", file=sys.stderr)
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Session {session_id}: Failed to delete file {file_info.file_name}: {e}", file=sys.stderr)
    
    async def _rate_limit(self):
        """Simple rate limiting."""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_time_between_requests:
            await asyncio.sleep(self.min_time_between_requests - time_since_last)
        self.last_request_time = time.time()
    
    async def _process_file(self, file_path: str, session: Session) -> ProcessedFile:
        """Upload file to Gemini and return processed file info."""
        # Check if already processed
        if file_path in session.processed_files:
            return session.processed_files[file_path]
        
        # Check if file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Get file info
        file_name = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        
        # Handle common file extensions that mimetypes doesn't recognize
        if not mime_type:
            ext = os.path.splitext(file_path)[1].lower()
            mime_type_map = {
                '.jsx': 'text/javascript',
                '.tsx': 'text/typescript',
                '.ts': 'text/typescript',
                '.vue': 'text/html',
                '.svelte': 'text/html',
                '.md': 'text/markdown',
                '.json': 'application/json',
                '.py': 'text/x-python',
                '.js': 'text/javascript',
                '.css': 'text/css',
                '.html': 'text/html',
                '.xml': 'text/xml',
                '.yaml': 'text/yaml',
                '.yml': 'text/yaml',
                '.toml': 'text/plain',
                '.ini': 'text/plain',
                '.cfg': 'text/plain',
                '.conf': 'text/plain',
                '.sh': 'text/x-shellscript',
                '.bat': 'text/plain',
                '.sql': 'text/x-sql'
            }
            mime_type = mime_type_map.get(ext, 'text/plain')
        
        print(f"[{datetime.now().isoformat()}] Session {session.session_id}: Uploading file {file_name} ({mime_type})", file=sys.stderr)
        
        # Upload to Gemini
        try:
            uploaded_file = client.files.upload(file=file_path)
            
            # Wait for processing with timeout
            timeout_seconds = 30
            wait_time = 0
            while uploaded_file.state == 'PROCESSING' and wait_time < timeout_seconds:
                print(f"[{datetime.now().isoformat()}] Session {session.session_id}: File {file_name} is processing... ({wait_time}s)", file=sys.stderr)
                await asyncio.sleep(1)
                wait_time += 1
                uploaded_file = client.files.get(name=uploaded_file.name)
            
            if uploaded_file.state == 'PROCESSING':
                raise Exception(f"File processing timeout after {timeout_seconds} seconds")
            
            if uploaded_file.state == 'FAILED':
                raise Exception(f"File upload failed: {getattr(uploaded_file, 'error', 'Unknown error')}")
            
            # Create processed file info
            processed_file = ProcessedFile(
                file_type='file_data',
                file_uri=uploaded_file.uri,
                mime_type=uploaded_file.mime_type,
                file_name=file_name,
                file_path=file_path,
                gemini_file_id=uploaded_file.name
            )
            
            # Store in session
            session.processed_files[file_path] = processed_file
            
            print(f"[{datetime.now().isoformat()}] Session {session.session_id}: File {file_name} uploaded successfully (URI: {uploaded_file.uri})", file=sys.stderr)
            return processed_file
            
        except Exception as e:
            raise Exception(f"Failed to process file {file_path}: {e}")
    
    def _get_or_create_session(self, session_id: Optional[str] = None) -> Session:
        """Get existing session or create new one."""
        if not session_id:
            import uuid
            session_id = str(uuid.uuid4())
        
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_used = datetime.now()
            return session
        
        # Create new session with system prompt
        chat = client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192,
                top_p=0.95,
                top_k=40,
                system_instruction=SYSTEM_PROMPT,
            )
        )
        
        session = Session(
            session_id=session_id,
            chat=chat,
            created=datetime.now(),
            last_used=datetime.now(),
            message_count=0
        )
        
        self.sessions[session_id] = session
        print(f"[{datetime.now().isoformat()}] New session created: {session_id}", file=sys.stderr)
        return session

# Create server instance
mcp = FastMCP("gemini-coding-assistant")
gemini_server = GeminiMCPServer()

@mcp.tool()
async def consult_gemini(
    specific_question: str,
    session_id: Optional[str] = None,
    problem_description: Optional[str] = None,
    code_context: Optional[str] = None,
    attached_files: Optional[List[str]] = None,
    file_descriptions: Optional[dict] = None,
    additional_context: Optional[str] = None,
    preferred_approach: str = "solution"
) -> str:
    """Start or continue a conversation with Gemini about complex coding problems. Supports follow-up questions in the same context.
    
    Args:
        specific_question: The specific question you want answered
        session_id: Optional session ID to continue a previous conversation
        problem_description: Detailed description of the coding problem (required for new sessions)
        code_context: All relevant code - will be cached for the session (required for new sessions)
        attached_files: Array of file paths to upload and attach to the conversation
        file_descriptions: Optional object mapping file paths to descriptions
        additional_context: Additional context, updates, or what changed since last question
        preferred_approach: Type of assistance needed (solution, review, debug, optimize, explain, follow-up)
    """
    
    await gemini_server._rate_limit()
    
    # Start cleanup task if needed
    gemini_server._ensure_cleanup_task_started()
    
    try:
        # Get or create session
        session = gemini_server._get_or_create_session(session_id)
        
        # For new sessions, require problem description and either code_context or attached_files
        if session.message_count == 0:
            if not problem_description:
                raise ValueError("problem_description is required for new sessions")
            if not code_context and not attached_files:
                raise ValueError("Either code_context or attached_files are required for new sessions")
            
            # Store initial context
            session.problem_description = problem_description
            session.code_context = code_context
            
            # Build initial context
            context_parts = [
                f"I'm Claude, an AI assistant, and I need your help with a complex coding problem. Here's the context:\n\n**Problem Description:**\n{problem_description}"
            ]
            
            # Add code context if provided
            if code_context:
                context_parts.append(f"\n**Code Context:**\n{code_context}")
            
            # Handle file attachments
            if attached_files:
                context_parts.append("\n**Attached Files:**")
                
                for file_path in attached_files:
                    try:
                        print(f"[{datetime.now().isoformat()}] Session {session.session_id}: Processing file: {file_path}", file=sys.stderr)
                        # Process file (upload to Gemini)
                        file_info = await gemini_server._process_file(file_path, session)
                        
                        # Add file description
                        description = file_descriptions.get(file_path, "") if file_descriptions else ""
                        if description:
                            description = f" - {description}"
                        context_parts.append(f"\n- {file_info.file_name}{description}")
                        
                        print(f"[{datetime.now().isoformat()}] Session {session.session_id}: File {file_info.file_name} processed successfully", file=sys.stderr)
                    
                    except Exception as file_error:
                        print(f"[{datetime.now().isoformat()}] Session {session.session_id}: Failed to process file {file_path}: {file_error}", file=sys.stderr)
                        # Continue with other files instead of failing completely
                        context_parts.append(f"\n- {file_path} (failed to upload: {str(file_error)})")
            
            context_parts.append("\n\nPlease help me solve this problem. I may have follow-up questions, so please maintain context throughout our conversation.")
            
            # Build message content - include text and uploaded file objects
            message_content = ["".join(context_parts)]
            
            # Add uploaded file objects for this session's new files
            for file_path in attached_files or []:
                if file_path in session.processed_files:
                    file_info = session.processed_files[file_path]
                    # Get the actual uploaded file object from Gemini
                    uploaded_file = client.files.get(name=file_info.gemini_file_id)
                    message_content.append(uploaded_file)
            
            # Send initial context
            response = await asyncio.get_event_loop().run_in_executor(
                None, session.chat.send_message, message_content
            )
            session.message_count += 1
            
            file_count = len(session.processed_files)
            code_length = len(code_context) if code_context else 0
            print(f"[{datetime.now().isoformat()}] Session {session.session_id}: Initial context sent ({code_length} chars, {file_count} files)", file=sys.stderr)
        
        # Build the question
        question_parts = [f"**Question:** {specific_question}"]
        
        if additional_context:
            question_parts.append(f"\n\n**Additional Context/Updates:**\n{additional_context}")
        
        if preferred_approach != "follow-up":
            question_parts.append(f"\n\n**Type of Help Needed:** {preferred_approach}")
        
        question_prompt = "".join(question_parts)
        
        # Log request
        print(f"[{datetime.now().isoformat()}] Session {session.session_id}: Question #{session.message_count + 1} ({preferred_approach})", file=sys.stderr)
        
        # Send message and get response
        response = await asyncio.get_event_loop().run_in_executor(
            None, session.chat.send_message, question_prompt
        )
        session.message_count += 1
        
        response_text = response.text
        
        return f"**Session ID:** {session.session_id}\n**Message #{session.message_count}**\n\n{response_text}\n\n---\n*Use session_id: \"{session.session_id}\" for follow-up questions*"
        
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Error: {e}", file=sys.stderr)
        
        error_message = str(e)
        if "RESOURCE_EXHAUSTED" in error_message:
            error_message = "Gemini API quota exceeded. Please try again later."
        elif "INVALID_ARGUMENT" in error_message:
            error_message = "Request too large. Try reducing code context size."
        
        return f"Error: {error_message}"

@mcp.tool()
async def list_sessions() -> str:
    """List all active Gemini consultation sessions."""
    session_list = []
    for session_id, session in gemini_server.sessions.items():
        session_info = {
            "id": session_id,
            "created": session.created.isoformat(),
            "last_used": session.last_used.isoformat(),
            "message_count": session.message_count,
            "problem_summary": (session.problem_description[:100] + "...") if session.problem_description else "No description",
            "file_count": len(session.processed_files),
            "has_code_context": bool(session.code_context)
        }
        session_list.append(session_info)
    
    if session_list:
        session_text = "\n\n".join([
            f"- **{s['id']}**\n  Messages: {s['message_count']}\n  Created: {s['created']}\n  Last used: {s['last_used']}\n  Files attached: {s['file_count']}\n  Code context: {'Yes' if s['has_code_context'] else 'No'}\n  Problem: {s['problem_summary']}"
            for s in session_list
        ])
        text = f"Active sessions:\n{session_text}"
    else:
        text = "No active sessions"
    
    return text

@mcp.tool()
async def end_session(session_id: str) -> str:
    """End a specific Gemini consultation session to free up memory."""
    if session_id in gemini_server.sessions:
        await gemini_server._cleanup_session_files(session_id)
        del gemini_server.sessions[session_id]
        print(f"[{datetime.now().isoformat()}] Session {session_id} ended by user", file=sys.stderr)
        return f"Session {session_id} has been ended"
    else:
        return f"Session {session_id} not found or already expired"

if __name__ == "__main__":
    print("Gemini Coding Assistant MCP Server v3.0 running (Python)", file=sys.stderr)
    print("Features: Session management, file attachments, context persistence, follow-up questions", file=sys.stderr)
    print("Ready to help with complex coding problems!", file=sys.stderr)
    
    mcp.run()