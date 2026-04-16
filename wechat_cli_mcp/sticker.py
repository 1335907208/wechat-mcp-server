"""Sticker parsing - Extract and manage WeChat stickers"""

import os
import re
import json
import hashlib
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import Counter
from xml.etree import ElementTree as ET


@dataclass
class StickerInfo:
    """Sticker information"""
    md5: str
    sticker_type: int  # 1=built-in, 2=custom, 3=store
    product_id: Optional[str] = None
    thumb_url: Optional[str] = None
    file_path: Optional[str] = None
    file_size: int = 0
    width: int = 0
    height: int = 0
    description: str = ""
    usage_count: int = 0
    first_seen: int = 0
    last_seen: int = 0


@dataclass
class StickerUsagePattern:
    """Sticker usage pattern analysis"""
    total_stickers: int = 0
    unique_stickers: int = 0
    frequency_per_100_msgs: float = 0.0
    top_stickers: List[Dict[str, Any]] = field(default_factory=list)
    type_distribution: Dict[str, int] = field(default_factory=dict)
    context_patterns: Dict[str, List[str]] = field(default_factory=dict)
    time_distribution: Dict[int, int] = field(default_factory=dict)


class StickerParser:
    """Parse and manage WeChat stickers"""
    
    # Sticker type mapping
    STICKER_TYPES = {
        1: "built-in",      # Built-in emoji
        2: "custom",        # Custom sticker
        3: "store",         # Store purchased
    }
    
    def __init__(self, wechat_data_dir: Optional[str] = None):
        self.wechat_data_dir = Path(wechat_data_dir) if wechat_data_dir else None
        self._sticker_cache: Dict[str, StickerInfo] = {}
        self._sticker_dir: Optional[Path] = None
    
    def _detect_sticker_dir(self) -> Optional[Path]:
        """Detect sticker storage directory"""
        if not self.wechat_data_dir:
            # Try to get from wechat-cli config
            config_path = Path.home() / '.wechat-cli' / 'config.json'
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        data_dir = config.get('data_dir')
                        if data_dir:
                            self.wechat_data_dir = Path(data_dir)
                except:
                    pass
        
        if not self.wechat_data_dir:
            return None
        
        # Common sticker locations
        possible_dirs = [
            self.wechat_data_dir / 'FileStorage' / 'CustomEmotion',
            self.wechat_data_dir / 'FileStorage' / 'MsgAttach' / 'Temp',
            self.wechat_data_dir / 'FileStorage' / 'Emotion',
            self.wechat_data_dir / 'Msg' / 'CustomEmotion',
        ]
        
        for dir_path in possible_dirs:
            if dir_path.exists():
                self._sticker_dir = dir_path
                return dir_path
        
        return None
    
    def parse_sticker_xml(self, content: str) -> Optional[StickerInfo]:
        """Parse sticker XML content from message"""
        if not content or '<emoji' not in content:
            return None
        
        try:
            # Handle CDATA and malformed XML
            content = content.strip()
            if not content.startswith('<'):
                # Extract XML from message content
                match = re.search(r'<emoji.*?</emoji>', content, re.DOTALL)
                if match:
                    content = match.group()
            
            root = ET.fromstring(content)
            emoji = root.find('.//emoji') or root if root.tag == 'emoji' else None
            
            if emoji is None:
                return None
            
            md5 = emoji.get('md5', '')
            if not md5:
                return None
            
            sticker_type = int(emoji.get('type', '2'))
            product_id = emoji.get('productid', '')
            thumb_url = emoji.get('thumburl', '')
            len_str = emoji.get('len', '0')
            width = int(emoji.get('width', '0'))
            height = int(emoji.get('height', '0'))
            
            return StickerInfo(
                md5=md5,
                sticker_type=sticker_type,
                product_id=product_id if product_id else None,
                thumb_url=thumb_url if thumb_url else None,
                file_size=int(len_str) if len_str.isdigit() else 0,
                width=width,
                height=height,
            )
            
        except ET.ParseError:
            # Try regex fallback
            md5_match = re.search(r'md5="([a-fA-F0-9]+)"', content)
            type_match = re.search(r'type="(\d+)"', content)
            
            if md5_match:
                return StickerInfo(
                    md5=md5_match.group(1),
                    sticker_type=int(type_match.group(1)) if type_match else 2,
                )
        
        except Exception as e:
            pass
        
        return None
    
    def find_sticker_file(self, md5: str) -> Optional[Path]:
        """Find sticker file by MD5"""
        if not self._sticker_dir:
            self._detect_sticker_dir()
        
        if not self._sticker_dir:
            return None
        
        # Search for file with MD5 in name
        for ext in ['.gif', '.png', '.jpg', '.jpeg', '.webp']:
            # Direct match
            candidate = self._sticker_dir / f"{md5}{ext}"
            if candidate.exists():
                return candidate
            
            # MD5 as part of filename
            for f in self._sticker_dir.iterdir():
                if md5 in f.name and f.suffix.lower() in ['.gif', '.png', '.jpg', '.jpeg', '.webp']:
                    return f
        
        return None
    
    def extract_stickers_from_messages(self, messages: List[Dict[str, Any]]) -> Dict[str, StickerInfo]:
        """Extract all stickers from message list"""
        stickers = {}
        
        for msg in messages:
            # Check if sticker message (type 47)
            msg_type = msg.get('type', '')
            if msg_type not in ['sticker', '47'] and 'sticker' not in str(msg_type).lower():
                continue
            
            content = msg.get('content', '')
            if not content:
                continue
            
            sticker = self.parse_sticker_xml(content)
            if sticker:
                timestamp = msg.get('create_time', 0)
                
                if sticker.md5 in stickers:
                    stickers[sticker.md5].usage_count += 1
                    stickers[sticker.md5].last_seen = timestamp
                else:
                    sticker.usage_count = 1
                    sticker.first_seen = timestamp
                    sticker.last_seen = timestamp
                    stickers[sticker.md5] = sticker
        
        return stickers
    
    def analyze_usage_patterns(
        self,
        stickers: Dict[str, StickerInfo],
        total_messages: int
    ) -> StickerUsagePattern:
        """Analyze sticker usage patterns"""
        pattern = StickerUsagePattern()
        
        if not stickers:
            return pattern
        
        pattern.total_stickers = sum(s.usage_count for s in stickers.values())
        pattern.unique_stickers = len(stickers)
        pattern.frequency_per_100_msgs = (pattern.total_stickers / total_messages * 100) if total_messages > 0 else 0
        
        # Top stickers
        sorted_stickers = sorted(stickers.values(), key=lambda s: s.usage_count, reverse=True)
        pattern.top_stickers = [
            {
                "md5": s.md5,
                "type": self.STICKER_TYPES.get(s.sticker_type, "unknown"),
                "usage_count": s.usage_count,
                "description": s.description,
            }
            for s in sorted_stickers[:10]
        ]
        
        # Type distribution
        type_counter = Counter()
        for s in stickers.values():
            type_name = self.STICKER_TYPES.get(s.sticker_type, "unknown")
            type_counter[type_name] += s.usage_count
        pattern.type_distribution = dict(type_counter)
        
        # Time distribution
        time_counter = Counter()
        for s in stickers.values():
            if s.last_seen:
                try:
                    from datetime import datetime
                    hour = datetime.fromtimestamp(s.last_seen).hour
                    time_counter[hour] += s.usage_count
                except:
                    pass
        pattern.time_distribution = dict(time_counter)
        
        return pattern
    
    def build_sticker_library(
        self,
        chat_name: str,
        limit: int = 1000,
        copy_files: bool = False,
        output_dir: Optional[str] = None
    ) -> Tuple[Dict[str, StickerInfo], StickerUsagePattern]:
        """Build sticker library from chat history"""
        
        # Fetch messages using context
        try:
            from .context import get_context
            from .core.messages import resolve_chat_context, collect_chat_history, MSG_TYPE_FILTERS
            
            ctx = get_context()
            chat_ctx = resolve_chat_context(chat_name, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
            
            messages = []
            if chat_ctx and chat_ctx.get('db_path'):
                names = ctx.get_contact_names()
                # Try to get sticker messages (type 47 = emoji)
                type_filter = MSG_TYPE_FILTERS.get('emoji')
                lines, _ = collect_chat_history(
                    chat_ctx, names, ctx.display_name_for_username,
                    start_ts=None, end_ts=None, limit=limit, offset=0,
                    msg_type_filter=type_filter, resolve_media=False, db_dir=ctx.db_dir,
                )
                
                # Convert lines to message format
                for line in lines:
                    messages.append({
                        'content': line,
                        'type': 'sticker',
                        'create_time': 0,
                    })
        except Exception as e:
            messages = []
        
        # Extract stickers
        stickers = self.extract_stickers_from_messages(messages)
        
        # Find file paths
        for md5, sticker in stickers.items():
            file_path = self.find_sticker_file(md5)
            if file_path:
                sticker.file_path = str(file_path)
        
        # Copy files if requested
        if copy_files and output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            for md5, sticker in stickers.items():
                if sticker.file_path:
                    src = Path(sticker.file_path)
                    if src.exists():
                        dst = output_path / f"{md5}{src.suffix}"
                        if not dst.exists():
                            shutil.copy2(src, dst)
                        sticker.file_path = str(dst)
        
        # Analyze patterns
        pattern = self.analyze_usage_patterns(stickers, len(messages))
        
        return stickers, pattern
    
    def get_sticker_description(self, sticker: StickerInfo) -> str:
        """Get human-readable description for sticker"""
        type_name = self.STICKER_TYPES.get(sticker.sticker_type, "unknown")
        
        parts = [f"[{type_name} sticker]"]
        
        if sticker.description:
            parts.append(sticker.description)
        
        if sticker.width and sticker.height:
            parts.append(f"({sticker.width}x{sticker.height})")
        
        if sticker.usage_count > 1:
            parts.append(f"used {sticker.usage_count} times")
        
        return " ".join(parts)


class StickerLibrary:
    """Manage sticker library for auto-reply"""
    
    def __init__(self, library_path: Optional[str] = None):
        self.library_path = Path(library_path) if library_path else Path.home() / '.wechat-cli' / 'stickers'
        self.library_file = self.library_path / 'library.json'
        self._library: Dict[str, Dict[str, Any]] = {}
        self._load_library()
    
    def _load_library(self):
        """Load library from file"""
        if self.library_file.exists():
            try:
                with open(self.library_file, 'r', encoding='utf-8') as f:
                    self._library = json.load(f)
            except:
                self._library = {}
    
    def _save_library(self):
        """Save library to file"""
        self.library_path.mkdir(parents=True, exist_ok=True)
        with open(self.library_file, 'w', encoding='utf-8') as f:
            json.dump(self._library, f, ensure_ascii=False, indent=2)
    
    def add_sticker(
        self,
        name: str,
        md5: str,
        file_path: str,
        description: str = "",
        tags: List[str] = None
    ):
        """Add sticker to library with name"""
        self._library[name] = {
            "md5": md5,
            "file_path": file_path,
            "description": description,
            "tags": tags or [],
            "usage_count": 0,
        }
        self._save_library()
    
    def get_sticker(self, name: str) -> Optional[Dict[str, Any]]:
        """Get sticker by name"""
        return self._library.get(name)
    
    def search_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Search stickers by tag"""
        results = []
        for name, info in self._library.items():
            if tag.lower() in [t.lower() for t in info.get('tags', [])]:
                results.append({"name": name, **info})
        return results
    
    def search_by_description(self, query: str) -> List[Dict[str, Any]]:
        """Search stickers by description"""
        results = []
        query_lower = query.lower()
        for name, info in self._library.items():
            if query_lower in info.get('description', '').lower():
                results.append({"name": name, **info})
            elif query_lower in name.lower():
                results.append({"name": name, **info})
        return results
    
    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """List all stickers"""
        return self._library.copy()
    
    def increment_usage(self, name: str):
        """Increment usage count"""
        if name in self._library:
            self._library[name]['usage_count'] = self._library[name].get('usage_count', 0) + 1
            self._save_library()
    
    def get_top_stickers(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get most used stickers"""
        sorted_stickers = sorted(
            self._library.items(),
            key=lambda x: x[1].get('usage_count', 0),
            reverse=True
        )
        return [{"name": name, **info} for name, info in sorted_stickers[:n]]


def parse_sticker_placeholder(text: str) -> List[Dict[str, str]]:
    """Parse sticker placeholders from text
    
    Examples:
        "Hello [sticker:dog]" -> [{"type": "text", "content": "Hello "}, {"type": "sticker", "name": "dog"}]
    """
    parts = []
    pattern = r'\[sticker:([^\]]+)\]'
    
    last_end = 0
    for match in re.finditer(pattern, text):
        # Text before sticker
        if match.start() > last_end:
            parts.append({
                "type": "text",
                "content": text[last_end:match.start()]
            })
        
        # Sticker
        parts.append({
            "type": "sticker",
            "name": match.group(1)
        })
        last_end = match.end()
    
    # Remaining text
    if last_end < len(text):
        parts.append({
            "type": "text",
            "content": text[last_end:]
        })
    
    return parts if parts else [{"type": "text", "content": text}]
