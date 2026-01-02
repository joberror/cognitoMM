"""
Logger Module

This module provides a robust logging system that captures terminal output (stdout/stderr)
and sends it to a Telegram channel. It uses a buffering system to avoid hitting
Telegram's rate limits.
"""

import sys
import asyncio
import io
import traceback
from datetime import datetime
import html

class TelegramLogger:
    def __init__(self, client=None, channel_id=None):
        self.client = client
        self.channel_id = channel_id
        self.buffer = []
        self.lock = asyncio.Lock()
        self.loop = None
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.is_capturing = False
        self.flush_task = None
        
        # Buffer settings
        self.FLUSH_INTERVAL = 3.0  # Seconds
        self.MAX_BUFFER_SIZE = 4000 # Telegram max is 4096, keep room for overhead
        
        # Patterns to ignore for Telegram logging (still printed to console)
        self.ignore_patterns = ["[DIAGNOSTIC]", "[INDEXED]"]

    def set_client(self, client, channel_id):
        """Update client and channel ID after initialization"""
        self.client = client
        self.channel_id = channel_id

    def start_capturing(self):
        """Start capturing stdout and stderr"""
        if self.is_capturing:
            return

        self.is_capturing = True
        sys.stdout = self._StreamWrapper(self, self.original_stdout, "stdout")
        sys.stderr = self._StreamWrapper(self, self.original_stderr, "stderr")
        
        # Start background flush task
        try:
            self.loop = asyncio.get_running_loop()
            self.flush_task = self.loop.create_task(self._periodic_flush())
        except RuntimeError:
            # Loop might not be running yet, task will need to be started manually or later
            pass

    def stop_capturing(self):
        """Stop capturing and restore original streams"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        self.is_capturing = False
        if self.flush_task:
            self.flush_task.cancel()

    def log(self, text, level="INFO"):
        """Log a message directly"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {text}"
        
        # Print to original stdout so it still shows in console
        print(formatted, file=self.original_stdout)
        
        # Add to buffer for Telegram
        self._add_to_buffer(formatted)

    def _add_to_buffer(self, text):
        """Add text to buffer in a thread-safe way"""
        if not self.channel_id:
            return

        # Simple string append, real thread safety handled in flush
        self.buffer.append(text)

    async def _periodic_flush(self):
        """Periodically flush buffer to Telegram"""
        while self.is_capturing:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            await self.flush()

    async def flush(self):
        """Send buffered logs to Telegram"""
        if not self.buffer or not self.client or not self.channel_id:
            return

        async with self.lock:
            if not self.buffer:
                return
            
            # Join messages
            messages = list(self.buffer)
            self.buffer.clear()
            
        full_text = "\n".join(messages)
        
        # Split into chunks if too long
        chunks = []
        current_chunk = ""
        
        for line in full_text.split('\n'):
            if len(current_chunk) + len(line) + 1 > self.MAX_BUFFER_SIZE:
                chunks.append(current_chunk)
                current_chunk = line
            else:
                if current_chunk:
                    current_chunk += "\n" + line
                else:
                    current_chunk = line
        
        if current_chunk:
            chunks.append(current_chunk)

        # Send chunks
        for chunk in chunks:
            try:
                # Use normal HTML output (no code block)
                escaped_text = html.escape(chunk)
                # Preserve bold/italic implementation if needed, but for now just raw text
                # We interpret newlines as newlines
                await self.client.send_message(
                    self.channel_id, 
                    escaped_text,
                    disable_web_page_preview=True
                )
            except Exception as e:
                # Fallback to stderr if sending fails, don't recurse
                print(f"Failed to send log to Telegram: {e}", file=self.original_stderr)

    class _StreamWrapper:
        """Wrapper for stdout/stderr to capture output"""
        def __init__(self, logger, original_stream, stream_name):
            self.logger = logger
            self.original_stream = original_stream
            self.stream_name = stream_name
            self.line_buffer = ""

        def write(self, text):
            # Write to original stream first (immediate)
            self.original_stream.write(text)
            self.original_stream.flush() 
            
            # For Telegram, buffer until newline to apply label cleanly
            if not text:
                return

            self.line_buffer += text
            
            if '\n' in self.line_buffer:
                lines = self.line_buffer.split('\n')
                # Process all complete lines
                for line in lines[:-1]:
                    # Filter out empty lines if desired, or keep them
                    # Apply label
                    label = "[TERMINAL]" if self.stream_name == "stdout" else "[ERROR]"
                    
                    # Check for ignore patterns
                    schip = False
                    if self.stream_name == "stdout":
                         for pattern in self.logger.ignore_patterns:
                             if pattern in line:
                                 schip = True
                                 break
                    
                    if not schip:
                        formatted = f"{label} {line}\n"
                        self.logger._add_to_buffer(formatted)
                
                # Keep remainder
                self.line_buffer = lines[-1]

        def flush(self):
            self.original_stream.flush()
            # If there's anything left in line buffer, send it?
            # Or wait. Usually flush is called meaningfully.
            if self.line_buffer:
                label = "[TERMINAL]" if self.stream_name == "stdout" else "[ERROR]"
                formatted = f"{label} {self.line_buffer}\n"
                self.logger._add_to_buffer(formatted)
                self.line_buffer = ""

        def isatty(self):
            return self.original_stream.isatty()

# Global logger instance
logger = TelegramLogger()
