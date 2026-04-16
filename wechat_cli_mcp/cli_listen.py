"""Interactive CLI for real-time WeChat message listening"""

import sys
import signal
import time
from pathlib import Path
from .listener import WeChatMessageListener, MessageEvent


class InteractiveListener:
    """Interactive CLI for real-time message listening"""
    
    def __init__(self, msg_dir: str = None):
        self.msg_dir = msg_dir
        self.listener = None
        self.running = False
        
    def on_message(self, event: MessageEvent):
        """Callback for new messages"""
        timestamp = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
        
        # Format message display
        sender = event.sender
        if event.is_self:
            sender = f"我 ({sender})"
        
        chat = event.chat_name
        if event.is_group:
            chat = f"[群] {chat}"
        
        content = event.content
        if not content:
            content = f"[{event.msg_type}]"
        
        # Print formatted message
        print(f"\n[{timestamp}] {chat}")
        print(f"  {sender}: {content}")
        print(">>> ", end="", flush=True)
    
    def start(self):
        """Start interactive listening mode"""
        # Auto-detect message directory if not provided
        if not self.msg_dir:
            print("正在检测微信消息目录...")
            self.msg_dir = self._detect_msg_dir()
            if not self.msg_dir:
                print("错误: 未找到微信消息目录")
                print("请使用 --msg-dir 参数指定目录")
                print("示例: wechat-listen --msg-dir \"D:\\xwechat_files\\wxid_xxx\\db_storage\\message\"")
                return False
            
            print(f"检测到消息目录: {self.msg_dir}")
        
        # Initialize listener
        self.listener = WeChatMessageListener(
            msg_dir=self.msg_dir,
            callback=self.on_message,
            interval=0.5,
            auto_detect=False
        )
        
        # Start listener
        print("\n启动监听器...")
        if not self.listener.start():
            print(f"错误: {self.listener.last_error}")
            return False
        
        print(f"监听器已启动，监控: {self.msg_dir}")
        print("按 Ctrl+C 退出")
        print("=" * 50)
        
        self.running = True
        
        # Setup signal handler for graceful shutdown
        def signal_handler(sig, frame):
            print("\n\n正在停止监听器...")
            self.running = False
            if self.listener:
                self.listener.stop()
            print("监听器已停止")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        # Keep running
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            signal_handler(None, None)
        
        return True
    
    def _detect_msg_dir(self) -> str:
        """Auto-detect WeChat message directory"""
        import os
        from pathlib import Path
        
        # Try common paths on Windows
        common_paths = [
            Path.home() / 'Documents' / 'WeChat Files',
            Path('C:/Users') / os.environ.get('USERNAME', '') / 'Documents' / 'WeChat Files',
        ]
        
        for base in common_paths:
            if base.exists():
                # Find wxid_* folders
                for user_dir in base.iterdir():
                    if user_dir.is_dir() and user_dir.name.startswith('wxid_'):
                        # Check both msg and db_storage/message
                        msg_dir = user_dir / 'msg'
                        db_storage_msg = user_dir / 'db_storage' / 'message'
                        
                        if db_storage_msg.exists() and list(db_storage_msg.glob('*.db-wal')):
                            return str(db_storage_msg)
                        elif msg_dir.exists() and list(msg_dir.glob('*.db-wal')):
                            return str(msg_dir)
        
        return None


def main():
    """Main entry point for interactive listening CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="实时监听微信新消息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 自动检测消息目录
  wechat-listen
  
  # 指定消息目录
  wechat-listen --msg-dir "D:\\xwechat_files\\wxid_xxx\\db_storage\\message"
  
  # 设置轮询间隔
  wechat-listen --interval 0.3
        """
    )
    
    parser.add_argument(
        '--msg-dir',
        type=str,
        default=None,
        help='微信消息目录路径（包含 *.db-wal 文件的目录）'
    )
    
    parser.add_argument(
        '--interval',
        type=float,
        default=0.5,
        help='轮询间隔（秒），默认 0.5'
    )
    
    args = parser.parse_args()
    
    # Start interactive listener
    cli = InteractiveListener(msg_dir=args.msg_dir)
    cli.listener = WeChatMessageListener(
        msg_dir=args.msg_dir,
        callback=cli.on_message,
        interval=args.interval,
        auto_detect=False if args.msg_dir else True
    )
    
    cli.start()


if __name__ == "__main__":
    main()
