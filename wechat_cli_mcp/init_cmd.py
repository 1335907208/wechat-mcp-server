"""Init command - Extract WeChat decryption keys"""

import json
import os
import sys

import click

from .core.config import STATE_DIR, CONFIG_FILE, KEYS_FILE, auto_detect_db_dir


@click.command()
@click.option("--db-dir", default=None, help="WeChat data directory path (auto-detect by default)")
@click.option("--force", is_flag=True, help="Force re-extract keys")
def init_cmd(db_dir, force):
    """Initialize wechat-cli-mcp: Extract keys and generate config"""
    click.echo("WeChat MCP Server Initialization")
    click.echo("=" * 40)

    # 1. Check if already initialized
    if os.path.exists(CONFIG_FILE) and os.path.exists(KEYS_FILE) and not force:
        click.echo(f"Already initialized (config: {CONFIG_FILE})")
        click.echo("Use --force to re-extract keys")
        return

    # 2. Create state directory
    os.makedirs(STATE_DIR, exist_ok=True)

    # 3. Determine db_dir
    if db_dir is None:
        db_dir = auto_detect_db_dir()
        if db_dir is None:
            click.echo("[!] Could not auto-detect WeChat data directory", err=True)
            click.echo("Please specify via --db-dir, e.g.:", err=True)
            click.echo("  wechat-cli-mcp init --db-dir ~/path/to/db_storage", err=True)
            sys.exit(1)
        click.echo(f"[+] Detected WeChat data directory: {db_dir}")
    else:
        db_dir = os.path.abspath(db_dir)
        if not os.path.isdir(db_dir):
            click.echo(f"[!] Directory not found: {db_dir}", err=True)
            sys.exit(1)
        click.echo(f"[+] Using specified data directory: {db_dir}")

    # 4. Extract keys
    click.echo("\nExtracting keys...")
    try:
        from .keys import extract_keys
        key_map = extract_keys(db_dir, KEYS_FILE)
    except RuntimeError as e:
        click.echo(f"\n[!] Key extraction failed: {e}", err=True)
        if "sudo" not in str(e).lower():
            click.echo("Hint: macOS/Linux may need sudo privileges", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"\n[!] Key extraction error: {e}", err=True)
        sys.exit(1)

    # 5. Write config
    cfg = {
        "db_dir": db_dir,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    click.echo(f"\n[+] Initialization complete!")
    click.echo(f"    Config: {CONFIG_FILE}")
    click.echo(f"    Keys: {KEYS_FILE}")
    click.echo(f"    Extracted {len(key_map)} database keys")
    click.echo("\nNow you can start the MCP server:")
    click.echo("  wechat-cli-mcp")
