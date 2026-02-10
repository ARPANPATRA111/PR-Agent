import os
import shutil
import gzip
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from config import settings

logger = logging.getLogger(__name__)


class BackupConfig:
    
    def __init__(
        self,
        backup_dir: str = "./data/backups",
        max_backups: int = 30,
        compress: bool = True,
        include_vector_store: bool = True,
    ):
        self.backup_dir = Path(backup_dir)
        self.max_backups = max_backups
        self.compress = compress
        self.include_vector_store = include_vector_store
        
        self.backup_dir.mkdir(parents=True, exist_ok=True)


backup_config = BackupConfig()


def get_db_path() -> Path:
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        if db_path.startswith("./"):
            db_path = Path(db_path)
        else:
            db_path = Path(db_path)
        return db_path
    raise ValueError(f"Unsupported database URL: {db_url}")


def create_backup(
    backup_name: Optional[str] = None,
    config: Optional[BackupConfig] = None,
) -> dict:
    config = config or backup_config
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    result = {
        "timestamp": timestamp,
        "success": False,
        "files": [],
        "errors": [],
    }
    
    try:
        if backup_name:
            backup_folder = config.backup_dir / f"{backup_name}_{timestamp}"
        else:
            backup_folder = config.backup_dir / f"backup_{timestamp}"
        
        backup_folder.mkdir(parents=True, exist_ok=True)
        
        db_path = get_db_path()
        if db_path.exists():
            backup_db_path = backup_folder / db_path.name
            
            if config.compress:
                compressed_path = backup_folder / f"{db_path.name}.gz"
                with open(db_path, 'rb') as f_in:
                    with gzip.open(compressed_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                result["files"].append(str(compressed_path))
                logger.info(f"Database backed up to: {compressed_path}")
            else:
                shutil.copy2(db_path, backup_db_path)
                result["files"].append(str(backup_db_path))
                logger.info(f"Database backed up to: {backup_db_path}")
        else:
            result["errors"].append(f"Database file not found: {db_path}")
        
        if config.include_vector_store:
            chroma_dir = Path(settings.chroma_persist_dir)
            if chroma_dir.exists():
                backup_chroma_dir = backup_folder / "chroma"
                shutil.copytree(chroma_dir, backup_chroma_dir)
                result["files"].append(str(backup_chroma_dir))
                logger.info(f"Vector store backed up to: {backup_chroma_dir}")
        
        manifest = {
            "timestamp": timestamp,
            "files": result["files"],
            "database_url": settings.database_url,
            "version": "1.1.0",
        }
        
        manifest_path = backup_folder / "manifest.json"
        import json
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        result["success"] = True
        result["backup_path"] = str(backup_folder)
        
        logger.info(f"Backup completed successfully: {backup_folder}")
        
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Backup failed: {e}", exc_info=True)
    
    return result


def restore_backup(backup_path: str) -> dict:
    result = {
        "success": False,
        "restored_files": [],
        "errors": [],
    }
    
    backup_folder = Path(backup_path)
    
    if not backup_folder.exists():
        result["errors"].append(f"Backup folder not found: {backup_path}")
        return result
    
    try:
        manifest_path = backup_folder / "manifest.json"
        if manifest_path.exists():
            import json
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            logger.info(f"Restoring from backup: {manifest.get('timestamp')}")
        
        db_path = get_db_path()
        
        compressed_db = list(backup_folder.glob("*.db.gz"))
        if compressed_db:
            with gzip.open(compressed_db[0], 'rb') as f_in:
                with open(db_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            result["restored_files"].append(str(db_path))
        else:
            db_backup = list(backup_folder.glob("*.db"))
            if db_backup:
                shutil.copy2(db_backup[0], db_path)
                result["restored_files"].append(str(db_path))
        
        chroma_backup = backup_folder / "chroma"
        if chroma_backup.exists():
            chroma_dir = Path(settings.chroma_persist_dir)
            if chroma_dir.exists():
                shutil.rmtree(chroma_dir)
            shutil.copytree(chroma_backup, chroma_dir)
            result["restored_files"].append(str(chroma_dir))
        
        result["success"] = True
        logger.info(f"Restore completed successfully from: {backup_path}")
        
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Restore failed: {e}", exc_info=True)
    
    return result


def list_backups(config: Optional[BackupConfig] = None) -> List[dict]:
    config = config or backup_config
    backups = []
    
    if not config.backup_dir.exists():
        return backups
    
    for backup_folder in sorted(config.backup_dir.iterdir(), reverse=True):
        if backup_folder.is_dir() and backup_folder.name.startswith("backup_"):
            manifest_path = backup_folder / "manifest.json"
            
            backup_info = {
                "name": backup_folder.name,
                "path": str(backup_folder),
                "timestamp": backup_folder.name.split("_", 1)[1] if "_" in backup_folder.name else None,
            }
            
            if manifest_path.exists():
                import json
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                backup_info.update(manifest)
            
            total_size = sum(f.stat().st_size for f in backup_folder.rglob("*") if f.is_file())
            backup_info["size_bytes"] = total_size
            backup_info["size_mb"] = round(total_size / (1024 * 1024), 2)
            
            backups.append(backup_info)
    
    return backups


def cleanup_old_backups(
    max_backups: Optional[int] = None,
    config: Optional[BackupConfig] = None,
) -> dict:
    config = config or backup_config
    max_backups = max_backups or config.max_backups
    
    result = {
        "removed": [],
        "kept": 0,
        "errors": [],
    }
    
    backups = list_backups(config)
    
    to_remove = backups[max_backups:]
    to_keep = backups[:max_backups]
    
    result["kept"] = len(to_keep)
    
    for backup in to_remove:
        try:
            backup_path = Path(backup["path"])
            shutil.rmtree(backup_path)
            result["removed"].append(backup["name"])
            logger.info(f"Removed old backup: {backup['name']}")
        except Exception as e:
            result["errors"].append(f"Failed to remove {backup['name']}: {e}")
    
    return result


def scheduled_backup():
    logger.info("Starting scheduled backup...")
    
    result = create_backup()
    
    if result["success"]:
        cleanup_result = cleanup_old_backups()
        logger.info(
            f"Backup complete. Kept {cleanup_result['kept']} backups, "
            f"removed {len(cleanup_result['removed'])}"
        )
    else:
        logger.error(f"Scheduled backup failed: {result['errors']}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Database Backup Manager")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    backup_parser = subparsers.add_parser("backup", help="Create a backup")
    backup_parser.add_argument("--name", help="Custom backup name")
    
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("path", help="Path to backup folder")
    
    subparsers.add_parser("list", help="List all backups")
    
    cleanup_parser = subparsers.add_parser("cleanup", help="Remove old backups")
    cleanup_parser.add_argument("--keep", type=int, default=30, help="Number to keep")
    
    args = parser.parse_args()
    
    if args.command == "backup":
        result = create_backup(backup_name=args.name)
        print(f"Backup {'succeeded' if result['success'] else 'failed'}")
        if result["files"]:
            print(f"Files: {result['files']}")
        if result["errors"]:
            print(f"Errors: {result['errors']}")
    
    elif args.command == "restore":
        result = restore_backup(args.path)
        print(f"Restore {'succeeded' if result['success'] else 'failed'}")
        if result["restored_files"]:
            print(f"Restored: {result['restored_files']}")
        if result["errors"]:
            print(f"Errors: {result['errors']}")
    
    elif args.command == "list":
        backups = list_backups()
        print(f"Found {len(backups)} backups:")
        for b in backups:
            print(f"  - {b['name']} ({b.get('size_mb', 0)} MB)")
    
    elif args.command == "cleanup":
        result = cleanup_old_backups(max_backups=args.keep)
        print(f"Kept {result['kept']} backups, removed {len(result['removed'])}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
