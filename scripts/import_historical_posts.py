#!/usr/bin/env python3

import re
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from memory import MemoryManager


def strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'^\*+|\*+$', '', text, flags=re.MULTILINE)
    return text


def parse_old_progress(file_path: str) -> list[dict]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    posts_raw = content.split("---")
    
    posts = []
    week_pattern = re.compile(r"𝐖𝐞𝐞𝐤-(\d+)", re.IGNORECASE)
    week_pattern_alt = re.compile(r"Week[- ]?(\d+)", re.IGNORECASE)
    
    for post_text in posts_raw:
        post_text = post_text.strip()
        if not post_text:
            continue
        
        match = week_pattern.search(post_text)
        if not match:
            match = week_pattern_alt.search(post_text)
        
        if match:
            week_num = int(match.group(1))
            
            clean_content = strip_markdown(post_text)
            
            base_date = datetime(2025, 1, 1)
            estimated_date = base_date + timedelta(weeks=week_num - 1)
            
            posts.append({
                "week_number": week_num,
                "content": clean_content,
                "published_at": estimated_date
            })
    
    return posts


def import_posts(telegram_id: int, file_path: str = None, clear_existing: bool = False):
    if file_path is None:
        file_path = Path(__file__).parent.parent / "OldProgress.txt"
    
    if not Path(file_path).exists():
        print(f"Error: {file_path} not found")
        return 0
    
    print(f"Parsing {file_path}...")
    posts = parse_old_progress(str(file_path))
    print(f"Found {len(posts)} historical posts")
    
    memory = MemoryManager()
    
    try:
        memory.get_or_create_user(
            telegram_id=telegram_id,
            first_name="Historical Import",
            username="historical_import"
        )
        print(f"User {telegram_id} ready")
    except Exception as e:
        print(f"User setup: {e}")
    
    if clear_existing:
        print("Clearing existing generated posts...")
        memory.clear_generated_posts(telegram_id)
        print("  ✓ Cleared linkedin_posts table")
    
    imported = 0
    skipped = 0
    
    for post_data in posts:
        try:
            report_id = memory.save_posted_report(
                telegram_id=telegram_id,
                week_number=post_data["week_number"],
                content=post_data["content"],
                published_at=post_data["published_at"],
                linkedin_url=None
            )
            print(f"  ✓ Imported Week {post_data['week_number']} to posted_reports (ID: {report_id})")
            imported += 1
            
        except Exception as e:
            print(f"  ✗ Failed to import Week {post_data.get('week_number', '?')}: {e}")
            skipped += 1
    
    print(f"\nImport complete: {imported} imported, {skipped} skipped")
    return imported


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Import historical LinkedIn posts to posted_reports")
    parser.add_argument(
        "--telegram-id", "-t",
        type=int,
        required=True,
        help="Your Telegram user ID"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to OldProgress.txt"
    )
    parser.add_argument(
        "--clear", "-c",
        action="store_true",
        help="Clear existing generated posts (linkedin_posts) before import"
    )
    
    args = parser.parse_args()
    
    import_posts(args.telegram_id, args.file, args.clear)
