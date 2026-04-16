"""WeChat context manager - Singleton AppContext wrapper"""

import os
import json
import atexit
from pathlib import Path
from typing import Optional

from .core.config import load_config, STATE_DIR
from .core.db_cache import DBCache
from .core.key_utils import strip_key_metadata
from .core.messages import find_msg_db_keys
from .core.contacts import get_contact_names, display_name_for_username


class WeChatContext:
    """Singleton context manager for WeChat data access"""
    
    _instance: Optional['WeChatContext'] = None
    
    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_path: str = None):
        if self._initialized:
            return
            
        self.cfg = load_config(config_path)
        self.db_dir = self.cfg["db_dir"]
        self.decrypted_dir = self.cfg["decrypted_dir"]
        self.keys_file = self.cfg["keys_file"]
        
        if not os.path.exists(self.keys_file):
            raise FileNotFoundError(
                f"Key file not found: {self.keys_file}\n"
                "Run: wechat-cli init"
            )
        
        with open(self.keys_file, encoding="utf-8") as f:
            self.all_keys = strip_key_metadata(json.load(f))
        
        self.cache = DBCache(self.all_keys, self.db_dir)
        atexit.register(self.cache.cleanup)
        
        self.msg_db_keys = find_msg_db_keys(self.all_keys)
        
        os.makedirs(STATE_DIR, exist_ok=True)
        self._initialized = True
    
    def get_contact_names(self) -> dict:
        """Get contact name mapping"""
        return get_contact_names(self.cache, self.decrypted_dir)
    
    def display_name_for_username(self, username: str, names: dict = None) -> str:
        """Get display name for username"""
        if names is None:
            names = self.get_contact_names()
        return display_name_for_username(username, names, self.db_dir, self.cache, self.decrypted_dir)


def get_context(config_path: str = None) -> WeChatContext:
    """Get or create the singleton WeChatContext"""
    return WeChatContext(config_path)
