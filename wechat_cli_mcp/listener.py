"""WeChat message listener - Monitor sessions for real-time message detection"""

import os
import json
import time
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Thread, Lock
from typing import Callable, Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class ListenerState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class MessageEvent:
    """Message event data"""
    sender: str
    content: str
    chat_name: str
    is_self: bool
    is_group: bool
    timestamp: int
    msg_type: str
    raw: Dict[str, Any]


class WeChatMessageListener:
    """Monitor WeChat sessions for new messages"""
    
    def __init__(
        self,
        msg_dir: Optional[str] = None,
        callback: Optional[Callable[[MessageEvent], None]] = None,
        interval: float = 1.0,
        auto_detect: bool = True
    ):
        self.msg_dir = Path(msg_dir) if msg_dir else None
        self.callback = callback
        self.interval = interval
        self.auto_detect = auto_detect
        
        self._state = ListenerState.STOPPED
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._message_buffer: List[MessageEvent] = []
        self._last_error: Optional[str] = None
        self._session_timestamps: Dict[str, int] = {}  # {username: last_timestamp}
    
    @property
    def state(self) -> ListenerState:
        return self._state
    
    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    def _detect_msg_dir(self) -> Optional[Path]:
        """Auto-detect WeChat message directory from wechat-cli config"""
        config_dir = Path.home() / '.wechat-cli'
        config_file = config_dir / 'config.json'
        
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    data_dir = config.get('data_dir')
                    if data_dir:
                        msg_dir = Path(data_dir) / 'Msg'
                        if msg_dir.exists():
                            return msg_dir
            except Exception:
                pass
        
        # Try common paths on Windows
        common_paths = [
            Path.home() / 'Documents' / 'WeChat Files',
            Path('C:/Users') / os.environ.get('USERNAME', '') / 'Documents' / 'WeChat Files',
        ]
        
        for base in common_paths:
            if base.exists():
                # Find wxid_* folders
                for user_dir in base.iterdir():
                    if user_dir.is_dir() and (user_dir.name.startswith('wxid_') or user_dir.name.startswith('WeChatFiles')):
                        msg_dir = user_dir / 'Msg'
                        if msg_dir.exists():
                            return msg_dir
        
        return None
    
    def _get_context(self):
        """Get WeChat context"""
        from .context import get_context
        return get_context()
    
    def _query_sessions(self) -> List[Dict[str, Any]]:
        """Query sessions list directly from database"""
        try:
            ctx = self._get_context()
            from .core.messages import decompress_content, format_msg_type
            
            path = ctx.cache.get(os.path.join("session", "session.db"))
            if not path:
                return []
            
            names = ctx.get_contact_names()
            with closing(sqlite3.connect(path)) as conn:
                rows = conn.execute("""
                    SELECT username, unread_count, summary, last_timestamp,
                           last_msg_type, last_msg_sender, last_sender_display_name
                    FROM SessionTable
                    WHERE last_timestamp > 0
                    ORDER BY last_timestamp DESC
                    LIMIT 50
                """).fetchall()
            
            results = []
            for r in rows:
                username, unread, summary, ts, msg_type, sender, sender_name = r
                display = names.get(username, username)
                is_group = '@chatroom' in username
                
                if isinstance(summary, bytes):
                    summary = decompress_content(summary, 4) or '(compressed)'
                if isinstance(summary, str) and ':\n' in summary:
                    summary = summary.split(':\n', 1)[1]
                
                sender_display = ''
                if is_group and sender:
                    sender_display = names.get(sender, sender_name or sender)
                
                results.append({
                    'chat': display,
                    'username': username,
                    'is_group': is_group,
                    'unread': unread or 0,
                    'last_message': str(summary or ''),
                    'msg_type': format_msg_type(msg_type),
                    'sender': sender_display,
                    'timestamp': ts,
                })
            
            return results
        except Exception as e:
            self._last_error = str(e)
            return []
    
    def _query_chat_history(self, username: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Query chat history for a specific session"""
        try:
            ctx = self._get_context()
            from .core.messages import resolve_chat_context, collect_chat_history
            
            chat_ctx = resolve_chat_context(username, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
            if not chat_ctx or not chat_ctx.get('db_path'):
                return []
            
            names = ctx.get_contact_names()
            lines, _ = collect_chat_history(
                chat_ctx, names, ctx.display_name_for_username,
                start_ts=None, end_ts=None, limit=limit, offset=0,
                msg_type_filter=None, resolve_media=False, db_dir=ctx.db_dir,
            )
            
            messages = []
            for line in lines:
                messages.append({
                    'raw_text': line,
                    'chat_name': chat_ctx.get('display_name', ''),
                    'username': username,
                    'is_group': chat_ctx.get('is_group', False),
                })
            return messages
        except Exception as e:
            self._last_error = str(e)
            return []
    
    def _check_new_messages(self) -> List[Dict[str, Any]]:
        """Check for new messages by comparing session timestamps"""
        new_messages = []
        sessions = self._query_sessions()
        
        for session in sessions:
            username = session.get('username', '')
            timestamp = session.get('timestamp', 0)
            
            with self._lock:
                last_ts = self._session_timestamps.get(username, 0)
            
            # New message detected
            if timestamp > last_ts and timestamp > 0:
                # Update timestamp
                with self._lock:
                    self._session_timestamps[username] = timestamp
                
                # Get the new message details
                chat_name = session.get('chat', '')
                last_message = session.get('last_message', '')
                sender = session.get('sender', '')
                is_group = session.get('is_group', False)
                msg_type = session.get('msg_type', 'text')
                
                # Create message event
                msg = {
                    'chat_name': chat_name,
                    'username': username,
                    'sender': sender,
                    'content': last_message,
                    'timestamp': timestamp,
                    'is_group': is_group,
                    'is_self': False,  # Can't determine from session
                    'msg_type': msg_type,
                    'raw': session,
                }
                new_messages.append(msg)
        
        return new_messages
    
    def _parse_message(self, msg: Dict[str, Any]) -> MessageEvent:
        """Parse raw message dict into MessageEvent"""
        return MessageEvent(
            sender=msg.get('sender', 'Unknown'),
            content=msg.get('content', ''),
            chat_name=msg.get('chat_name', ''),
            is_self=msg.get('is_self', False),
            is_group=msg.get('is_group', False),
            timestamp=msg.get('timestamp', 0),
            msg_type=msg.get('msg_type', 'text'),
            raw=msg
        )
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        # Initialize session timestamps
        sessions = self._query_sessions()
        for session in sessions:
            username = session.get('username', '')
            timestamp = session.get('timestamp', 0)
            if username and timestamp:
                with self._lock:
                    self._session_timestamps[username] = timestamp
        
        self._state = ListenerState.RUNNING
        
        while self._state == ListenerState.RUNNING:
            try:
                # Check for new messages
                messages = self._check_new_messages()
                
                # Process each message
                for msg in messages:
                    event = self._parse_message(msg)
                    
                    # Buffer the message
                    with self._lock:
                        self._message_buffer.append(event)
                    
                    # Trigger callback
                    if self.callback:
                        try:
                            self.callback(event)
                        except Exception as e:
                            self._last_error = f"Callback error: {e}"
            
            except Exception as e:
                self._last_error = str(e)
            
            time.sleep(self.interval)
    
    def start(self) -> bool:
        """Start listening for new messages"""
        if self._state == ListenerState.RUNNING:
            return True
        
        # Auto-detect message directory if not provided
        if not self.msg_dir and self.auto_detect:
            self.msg_dir = self._detect_msg_dir()
        
        # msg_dir is optional now, we use wechat-cli directly
        
        self._state = ListenerState.STARTING
        self._thread = Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        
        # Wait for thread to start
        timeout = 5
        while self._state == ListenerState.STARTING and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        
        return self._state == ListenerState.RUNNING
    
    def stop(self):
        """Stop listening"""
        self._state = ListenerState.STOPPED
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
    
    def get_buffered_messages(self, clear: bool = True) -> List[MessageEvent]:
        """Get buffered messages"""
        with self._lock:
            messages = self._message_buffer.copy()
            if clear:
                self._message_buffer.clear()
        return messages
    
    def clear_buffer(self):
        """Clear message buffer"""
        with self._lock:
            self._message_buffer.clear()


# Global listener instance for MCP tools
_global_listener: Optional[WeChatMessageListener] = None
_listener_callbacks: List[Callable[[MessageEvent], None]] = []


def get_listener() -> WeChatMessageListener:
    """Get or create global listener instance"""
    global _global_listener
    
    if _global_listener is None:
        _global_listener = WeChatMessageListener(
            callback=_dispatch_message,
            auto_detect=True
        )
    
    return _global_listener


def _dispatch_message(event: MessageEvent):
    """Dispatch message to all registered callbacks"""
    for callback in _listener_callbacks:
        try:
            callback(event)
        except Exception:
            pass


def register_callback(callback: Callable[[MessageEvent], None]):
    """Register a callback for new messages"""
    _listener_callbacks.append(callback)


def unregister_callback(callback: Callable[[MessageEvent], None]):
    """Unregister a callback"""
    if callback in _listener_callbacks:
        _listener_callbacks.remove(callback)
