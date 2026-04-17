#!/usr/bin/env python3
"""MCP server for wechat-cli using FastMCP"""

import os
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wechat-cli-mcp")

# Set UTF-8 environment for Windows
if os.name == 'nt':
    os.environ['PYTHONIOENCODING'] = 'utf-8'


def _get_context():
    """Get WeChat context singleton"""
    from .context import get_context
    return get_context()


def _json_output(data) -> str:
    """Format data as JSON string"""
    return json.dumps(data, ensure_ascii=False, indent=2)


# ============== Sessions ==============

@mcp.tool()
def wechat_sessions(limit: int = 20) -> str:
    """List recent WeChat chat sessions/conversations"""
    try:
        ctx = _get_context()
        from .core.messages import decompress_content, format_msg_type
        
        path = ctx.cache.get(os.path.join("session", "session.db"))
        if not path:
            return "Error: Cannot decrypt session.db"
        
        names = ctx.get_contact_names()
        with closing(sqlite3.connect(path)) as conn:
            rows = conn.execute("""
                SELECT username, unread_count, summary, last_timestamp,
                       last_msg_type, last_msg_sender, last_sender_display_name
                FROM SessionTable
                WHERE last_timestamp > 0
                ORDER BY last_timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
        
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
                'time': datetime.fromtimestamp(ts).strftime('%m-%d %H:%M'),
            })
        
        return _json_output(results)
    except Exception as e:
        return f"Error: {str(e)}"


# ============== History ==============

@mcp.tool()
def wechat_history(chat_name: str, limit: int = 50, msg_type: str = None) -> str:
    """Read chat history from a specific WeChat conversation"""
    try:
        ctx = _get_context()
        from .core.messages import (
            MSG_TYPE_FILTERS, resolve_chat_context, collect_chat_history,
            parse_time_range, validate_pagination
        )
        
        validate_pagination(limit, 0, limit_max=None)
        
        chat_ctx = resolve_chat_context(chat_name, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
        if not chat_ctx:
            return f"Error: Chat not found: {chat_name}"
        if not chat_ctx['db_path']:
            return f"Error: No message records for {chat_ctx['display_name']}"
        
        names = ctx.get_contact_names()
        type_filter = MSG_TYPE_FILTERS[msg_type] if msg_type else None
        lines, failures = collect_chat_history(
            chat_ctx, names, ctx.display_name_for_username,
            start_ts=None, end_ts=None, limit=limit, offset=0,
            msg_type_filter=type_filter, resolve_media=False, db_dir=ctx.db_dir,
        )
        
        return _json_output({
            'chat': chat_ctx['display_name'],
            'username': chat_ctx['username'],
            'is_group': chat_ctx['is_group'],
            'count': len(lines),
            'messages': lines,
            'failures': failures if failures else None,
        })
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Search ==============

@mcp.tool()
def wechat_search(keyword: str, chat_name: str = None, limit: int = 20) -> str:
    """Search WeChat messages by keyword"""
    try:
        ctx = _get_context()
        from .core.messages import (
            MSG_TYPE_FILTERS, resolve_chat_context, collect_chat_search,
            search_all_messages, validate_pagination, _candidate_page_size, _page_ranked_entries
        )
        
        validate_pagination(limit, 0)
        names = ctx.get_contact_names()
        candidate_limit = _candidate_page_size(limit, 0)
        
        if chat_name:
            chat_ctx = resolve_chat_context(chat_name, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
            if not chat_ctx:
                return f"Error: Chat not found: {chat_name}"
            if not chat_ctx['db_path']:
                return f"Error: No message records for {chat_ctx['display_name']}"
            entries, failures = collect_chat_search(
                chat_ctx, names, keyword, ctx.display_name_for_username,
                start_ts=None, end_ts=None, candidate_limit=candidate_limit,
            )
            scope = chat_ctx['display_name']
        else:
            entries, failures = search_all_messages(
                ctx.msg_db_keys, ctx.cache, names, keyword, ctx.display_name_for_username,
                start_ts=None, end_ts=None, candidate_limit=candidate_limit,
            )
            scope = "all messages"
        
        paged = _page_ranked_entries(entries, limit, 0)
        
        return _json_output({
            'scope': scope,
            'keyword': keyword,
            'count': len(paged),
            'results': [item[1] for item in paged],
            'failures': failures if failures else None,
        })
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Contacts ==============

@mcp.tool()
def wechat_contacts(query: str = None, detail: str = None) -> str:
    """Search WeChat contacts"""
    try:
        ctx = _get_context()
        from .core.contacts import get_contact_full, resolve_username, get_contact_detail
        
        if detail:
            names = ctx.get_contact_names()
            username = resolve_username(detail, ctx.cache, ctx.decrypted_dir)
            if not username:
                username = detail
            info = get_contact_detail(username, ctx.cache, ctx.decrypted_dir)
            if not info:
                return f"Error: Contact not found: {detail}"
            return _json_output(info)
        
        full = get_contact_full(ctx.cache, ctx.decrypted_dir)
        
        if query:
            q_lower = query.lower()
            matched = [c for c in full if q_lower in c.get('nick_name', '').lower()
                       or q_lower in c.get('remark', '').lower()
                       or q_lower in c.get('username', '').lower()]
        else:
            matched = full
        
        return _json_output(matched[:50])
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Unread ==============

@mcp.tool()
def wechat_unread(limit: int = 20) -> str:
    """Show unread WeChat sessions"""
    try:
        ctx = _get_context()
        from .core.messages import decompress_content, format_msg_type
        
        path = ctx.cache.get(os.path.join("session", "session.db"))
        if not path:
            return "Error: Cannot decrypt session.db"
        
        names = ctx.get_contact_names()
        with closing(sqlite3.connect(path)) as conn:
            rows = conn.execute("""
                SELECT username, unread_count, summary, last_timestamp,
                       last_msg_type, last_msg_sender, last_sender_display_name
                FROM SessionTable
                WHERE unread_count > 0
                ORDER BY last_timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
        
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
                'time': datetime.fromtimestamp(ts).strftime('%m-%d %H:%M'),
            })
        
        return _json_output(results)
    except Exception as e:
        return f"Error: {str(e)}"


# ============== New Messages ==============

@mcp.tool()
def wechat_new_messages() -> str:
    """Get new WeChat messages since last check (incremental)"""
    try:
        ctx = _get_context()
        from .core.config import STATE_DIR
        from .core.messages import decompress_content, format_msg_type
        
        STATE_FILE = os.path.join(STATE_DIR, "last_check.json")
        
        def _load_last_state():
            if not os.path.exists(STATE_FILE):
                return {}
            try:
                with open(STATE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        
        def _save_last_state(state):
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(STATE_FILE, 'w', encoding="utf-8") as f:
                json.dump(state, f)
        
        path = ctx.cache.get(os.path.join("session", "session.db"))
        if not path:
            return "Error: Cannot decrypt session.db"
        
        names = ctx.get_contact_names()
        with closing(sqlite3.connect(path)) as conn:
            rows = conn.execute("""
                SELECT username, unread_count, summary, last_timestamp,
                       last_msg_type, last_msg_sender, last_sender_display_name
                FROM SessionTable
                WHERE last_timestamp > 0
                ORDER BY last_timestamp DESC
            """).fetchall()
        
        curr_state = {}
        for r in rows:
            username, unread, summary, ts, msg_type, sender, sender_name = r
            curr_state[username] = {
                'unread': unread, 'summary': summary, 'timestamp': ts,
                'msg_type': msg_type, 'sender': sender or '', 'sender_name': sender_name or '',
            }
        
        last_state = _load_last_state()
        
        if not last_state:
            _save_last_state({u: s['timestamp'] for u, s in curr_state.items()})
            
            unread_msgs = []
            for username, s in curr_state.items():
                if s['unread'] and s['unread'] > 0:
                    display = names.get(username, username)
                    is_group = '@chatroom' in username
                    summary = s['summary']
                    if isinstance(summary, bytes):
                        summary = decompress_content(summary, 4) or '(compressed)'
                    if isinstance(summary, str) and ':\n' in summary:
                        summary = summary.split(':\n', 1)[1]
                    time_str = datetime.fromtimestamp(s['timestamp']).strftime('%H:%M')
                    unread_msgs.append({
                        'chat': display,
                        'username': username,
                        'is_group': is_group,
                        'unread': s['unread'],
                        'last_message': str(summary or ''),
                        'msg_type': format_msg_type(s['msg_type']),
                        'time': time_str,
                        'timestamp': s['timestamp'],
                    })
            
            return _json_output({'first_call': True, 'unread_count': len(unread_msgs), 'messages': unread_msgs})
        
        new_msgs = []
        for username, s in curr_state.items():
            prev_ts = last_state.get(username, 0)
            if s['timestamp'] > prev_ts:
                display = names.get(username, username)
                is_group = '@chatroom' in username
                summary = s['summary']
                if isinstance(summary, bytes):
                    summary = decompress_content(summary, 4) or '(compressed)'
                if isinstance(summary, str) and ':\n' in summary:
                    summary = summary.split(':\n', 1)[1]
                
                sender_display = ''
                if is_group and s['sender']:
                    sender_display = names.get(s['sender'], s['sender_name'] or s['sender'])
                
                new_msgs.append({
                    'chat': display,
                    'username': username,
                    'is_group': is_group,
                    'last_message': str(summary or ''),
                    'msg_type': format_msg_type(s['msg_type']),
                    'sender': sender_display,
                    'time': datetime.fromtimestamp(s['timestamp']).strftime('%H:%M:%S'),
                    'timestamp': s['timestamp'],
                })
        
        _save_last_state({u: s['timestamp'] for u, s in curr_state.items()})
        new_msgs.sort(key=lambda m: m['timestamp'])
        
        return _json_output({'first_call': False, 'new_count': len(new_msgs), 'messages': new_msgs})
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Members ==============

@mcp.tool()
def wechat_members(group_name: str) -> str:
    """List members of a WeChat group"""
    try:
        ctx = _get_context()
        from .core.contacts import resolve_username, get_group_members
        
        username = resolve_username(group_name, ctx.cache, ctx.decrypted_dir)
        if not username:
            return f"Error: Group not found: {group_name}"
        
        if '@chatroom' not in username:
            return f"Error: {group_name} is not a group"
        
        names = ctx.get_contact_names()
        display_name = names.get(username, username)
        result = get_group_members(username, ctx.cache, ctx.decrypted_dir)
        
        return _json_output({
            'group': display_name,
            'username': username,
            'member_count': len(result['members']),
            'owner': result['owner'],
            'members': result['members'],
        })
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Stats ==============

@mcp.tool()
def wechat_stats(chat_name: str, start_time: str = None, end_time: str = None) -> str:
    """Get statistics for a WeChat chat"""
    try:
        ctx = _get_context()
        from .core.messages import (
            resolve_chat_context, collect_chat_stats, parse_time_range
        )
        
        start_ts, end_ts = parse_time_range(start_time or '', end_time or '')
        
        chat_ctx = resolve_chat_context(chat_name, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
        if not chat_ctx:
            return f"Error: Chat not found: {chat_name}"
        if not chat_ctx['db_path']:
            return f"Error: No message records for {chat_ctx['display_name']}"
        
        names = ctx.get_contact_names()
        result = collect_chat_stats(
            chat_ctx, names, ctx.display_name_for_username,
            start_ts=start_ts, end_ts=end_ts,
        )
        
        return _json_output({
            'chat': chat_ctx['display_name'],
            'username': chat_ctx['username'],
            'is_group': chat_ctx['is_group'],
            **result,
        })
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Favorites ==============

@mcp.tool()
def wechat_favorites(msg_type: str = None, query: str = None) -> str:
    """List WeChat favorites/bookmarks"""
    try:
        ctx = _get_context()
        import xml.etree.ElementTree as ET
        
        _FAV_TYPE_MAP = {
            1: 'text', 2: 'image', 5: 'article', 19: 'card', 20: 'video',
        }
        _FAV_TYPE_FILTERS = {
            'text': 1, 'image': 2, 'article': 5, 'card': 19, 'video': 20,
        }
        
        def _parse_fav_content(content, fav_type):
            if not content:
                return ''
            try:
                root = ET.fromstring(content)
            except ET.ParseError:
                return ''
            item = root if root.tag == 'favitem' else root.find('.//favitem')
            if item is None:
                return ''
            
            if fav_type == 1:
                return (item.findtext('desc') or '').strip()
            if fav_type == 2:
                return '[Image]'
            if fav_type == 5:
                title = (item.findtext('.//pagetitle') or '').strip()
                desc = (item.findtext('.//pagedesc') or '').strip()
                return f"{title} - {desc}" if desc else title
            if fav_type == 19:
                return (item.findtext('desc') or '').strip()
            if fav_type == 20:
                nickname = (item.findtext('.//nickname') or '').strip()
                desc = (item.findtext('.//desc') or '').strip()
                parts = [p for p in [nickname, desc] if p]
                return ' '.join(parts) if parts else '[Video]'
            desc = (item.findtext('desc') or '').strip()
            return desc if desc else '[Favorite]'
        
        fav_path = None
        pre_decrypted = os.path.join(ctx.decrypted_dir, "favorite", "favorite.db")
        if os.path.exists(pre_decrypted):
            fav_path = pre_decrypted
        else:
            fav_path = ctx.cache.get(os.path.join("favorite", "favorite.db"))
        if not fav_path:
            return "Error: Cannot access favorite.db"
        
        names = ctx.get_contact_names()
        
        with closing(sqlite3.connect(fav_path)) as conn:
            where_parts = []
            params = []
            
            if msg_type and msg_type in _FAV_TYPE_FILTERS:
                where_parts.append('type = ?')
                params.append(_FAV_TYPE_FILTERS[msg_type])
            
            if query:
                where_parts.append('content LIKE ?')
                params.append(f'%{query}%')
            
            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ''
            
            rows = conn.execute(f"""
                SELECT local_id, type, update_time, content, fromusr, realchatname
                FROM fav_db_item
                {where_sql}
                ORDER BY update_time DESC
                LIMIT 20
            """, (*params,)).fetchall()
        
        results = []
        for local_id, typ, ts, content, fromusr, realchat in rows:
            from_display = names.get(fromusr, fromusr) if fromusr else ''
            chat_display = names.get(realchat, realchat) if realchat else ''
            summary = _parse_fav_content(content, typ)
            
            results.append({
                'id': local_id,
                'type': _FAV_TYPE_MAP.get(typ, f'type={typ}'),
                'time': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M'),
                'summary': summary,
                'from': from_display,
                'source_chat': chat_display,
            })
        
        return _json_output({'count': len(results), 'favorites': results})
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Skill Distillation Tools ==============

@mcp.tool()
def wechat_distill_skill(
    chat_names: str,
    message_limit: int = 500,
    output_format: str = "markdown"
) -> str:
    """Distill personal communication style from chat history into an Agent Skills compliant SKILL.md.
    
    Args:
        chat_names: Comma-separated list of chat names to analyze
        message_limit: Maximum messages to analyze per chat
        output_format: 'markdown' (Agent Skills SKILL.md) or 'json'
    
    Returns:
        Agent Skills compliant skill data with YAML frontmatter, style rules, and few-shot examples
    """
    try:
        from .distill import SkillDistiller
        
        chat_list = [name.strip() for name in chat_names.split(",")]
        distiller = SkillDistiller()
        
        skill = distiller.distill(chat_list, message_limit=message_limit)
        
        if output_format == "markdown":
            return distiller.to_markdown(skill)
        else:
            return distiller.to_json(skill)
            
    except ImportError as e:
        return f"Error: Missing dependencies. Run: pip install openai anthropic jinja2. Details: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_save_skill(
    chat_names: str,
    output_path: str,
    message_limit: int = 500,
    output_format: str = "markdown"
) -> str:
    """Distill and save skill to file as Agent Skills compliant SKILL.md.
    
    Args:
        chat_names: Comma-separated list of chat names
        output_path: Path to save the skill file (will create SKILL.md per Agent Skills spec)
        message_limit: Maximum messages per chat
        output_format: 'markdown' (Agent Skills SKILL.md) or 'json'
    
    Returns:
        Path to saved SKILL.md file or error message
    """
    try:
        from .distill import SkillDistiller
        
        chat_list = [name.strip() for name in chat_names.split(",")]
        distiller = SkillDistiller()
        
        skill = distiller.distill(chat_list, message_limit=message_limit)
        saved_path = distiller.save_skill(skill, output_path, format=output_format)
        
        return f"Skill saved to: {saved_path}"
        
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Message Listener Tools ==============

@mcp.tool()
def wechat_start_listener(msg_dir: str = None, interval: float = 0.5) -> str:
    """Start listening for new WeChat messages.

    The listener monitors database changes and buffers new messages.
    Use wechat_get_buffered_messages to retrieve them.

    Args:
        msg_dir: WeChat message directory path (e.g., "D:\\xwechat_files\\wxid_xxx\\msg"). If not provided, will auto-detect.
        interval: Polling interval in seconds (default 0.5)

    Returns:
        Status message
    """
    try:
        from .listener import get_listener

        listener = get_listener()

        if listener.state.name == "RUNNING":
            return "Listener is already running"

        # Update msg_dir if provided
        if msg_dir:
            from pathlib import Path
            listener.msg_dir = Path(msg_dir)
            listener.auto_detect = False

        success = listener.start()

        if success:
            return f"Listener started successfully. Monitoring: {listener.msg_dir}"
        else:
            return f"Failed to start listener: {listener.last_error}"

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_stop_listener() -> str:
    """Stop the message listener.
    
    Returns:
        Status message
    """
    try:
        from .listener import get_listener
        
        listener = get_listener()
        listener.stop()
        
        return "Listener stopped"
        
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_listener_status() -> str:
    """Get the current status of the message listener.

    Returns:
        Listener state and statistics
    """
    try:
        from .listener import get_listener

        listener = get_listener()

        buffered_count = len(listener.get_buffered_messages(clear=False))

        status = {
            "state": listener.state.value,
            "message_dir": str(listener.msg_dir) if listener.msg_dir else "not detected",
            "buffered_messages": buffered_count,
            "has_new_messages": buffered_count > 0,
            "last_error": listener.last_error,
        }

        return json.dumps(status, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_get_buffered_messages(clear: bool = True) -> str:
    """Get buffered messages from the listener.
    
    Args:
        clear: Whether to clear the buffer after reading (default True)
    
    Returns:
        JSON array of buffered messages
    """
    try:
        from .listener import get_listener
        
        listener = get_listener()
        messages = listener.get_buffered_messages(clear=clear)
        
        result = []
        for msg in messages:
            result.append({
                "sender": msg.sender,
                "content": msg.content,
                "chat_name": msg.chat_name,
                "is_self": msg.is_self,
                "is_group": msg.is_group,
                "timestamp": msg.timestamp,
                "msg_type": msg.msg_type,
            })
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"Error: {str(e)}"


# ============== Sticker Tools ==============

@mcp.tool()
def wechat_build_sticker_library(
    chat_name: str,
    limit: int = 500,
    copy_files: bool = False,
    output_dir: str = None
) -> str:
    """Build sticker library from chat history.
    
    Extracts sticker information including MD5, type, usage count.
    
    Args:
        chat_name: Chat name to analyze
        limit: Maximum messages to scan
        copy_files: Whether to copy sticker files to output_dir
        output_dir: Directory to copy sticker files (if copy_files=True)
    
    Returns:
        JSON with sticker library and usage patterns
    """
    try:
        from .sticker import StickerParser
        
        parser = StickerParser()
        stickers, pattern = parser.build_sticker_library(
            chat_name,
            limit=limit,
            copy_files=copy_files,
            output_dir=output_dir
        )
        
        result = {
            "total_stickers": len(stickers),
            "usage_pattern": {
                "total_count": pattern.total_stickers,
                "unique_count": pattern.unique_stickers,
                "frequency_per_100_msgs": pattern.frequency_per_100_msgs,
                "top_stickers": pattern.top_stickers[:5],
                "type_distribution": pattern.type_distribution,
            },
            "stickers": [
                {
                    "md5": s.md5,
                    "type": parser.STICKER_TYPES.get(s.sticker_type, "unknown"),
                    "usage_count": s.usage_count,
                    "file_path": s.file_path,
                }
                for s in sorted(stickers.values(), key=lambda x: x.usage_count, reverse=True)[:20]
            ]
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_search_stickers(query: str, limit: int = 10) -> str:
    """Search sticker library by name or description.
    
    Args:
        query: Search query
        limit: Maximum results to return
    
    Returns:
        JSON array of matching stickers
    """
    try:
        from .sticker import StickerLibrary
        
        library = StickerLibrary()
        results = library.search_by_description(query)[:limit]
        
        return json.dumps(results, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_list_stickers() -> str:
    """List all stickers in the library.
    
    Returns:
        JSON object with all stickers
    """
    try:
        from .sticker import StickerLibrary
        
        library = StickerLibrary()
        stickers = library.list_all()
        
        return json.dumps(stickers, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_add_sticker(
    name: str,
    md5: str,
    file_path: str,
    description: str = "",
    tags: str = ""
) -> str:
    """Add a sticker to the library.
    
    Args:
        name: Name for the sticker (used in [sticker:name] placeholders)
        md5: MD5 hash of the sticker
        file_path: Path to the sticker file
        description: Description of the sticker
        tags: Comma-separated tags for searching
    
    Returns:
        Status message
    """
    try:
        from .sticker import StickerLibrary
        
        library = StickerLibrary()
        tag_list = [t.strip() for t in tags.split(",")] if tags else []
        
        library.add_sticker(name, md5, file_path, description, tag_list)
        
        return f"Sticker '{name}' added to library"
        
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def wechat_parse_sticker_placeholder(text: str) -> str:
    """Parse sticker placeholders from text.
    
    Example: "Hello [sticker:dog]" -> [{"type": "text", "content": "Hello "}, {"type": "sticker", "name": "dog"}]
    
    Args:
        text: Text with sticker placeholders
    
    Returns:
        JSON array of parsed parts
    """
    try:
        from .sticker import parse_sticker_placeholder
        
        parts = parse_sticker_placeholder(text)
        return json.dumps(parts, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"Error: {str(e)}"


def main():
    """Main entry point - supports init and MCP server modes"""
    import sys
    import os
    
    # Check for init subcommand
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from .init_cmd import init_cmd
        sys.argv.pop(1)  # Remove 'init' from argv
        init_cmd(standalone_mode=False)
        return
    
    # MCP server mode
    if os.environ.get("MCP_TRANSPORT") == "sse" or "--sse" in sys.argv:
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
