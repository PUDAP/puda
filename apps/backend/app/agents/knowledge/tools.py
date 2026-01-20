"""Tools for the knowledge agent to read and write markdown files."""
from pathlib import Path
from typing import List, Optional
from datetime import datetime


# Knowledge base directory - relative to backend root
_KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent.parent.parent / "knowledge"


def ensure_knowledge_dir() -> Path:
    """Ensure the knowledge directory exists and return its path.
    
    Returns:
        Path to the knowledge directory
    """
    _KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    return _KNOWLEDGE_BASE_DIR


def save_knowledge(content: str, conversation_id: str) -> str:
    """Save knowledge content to a markdown file organized by conversation_id.
    
    Args:
        content: The knowledge content to save (markdown formatted)
        conversation_id: The conversation ID to use as the filename ({conversation_id}.md)
        
    Returns:
        Path to the saved file
    """
    knowledge_dir = ensure_knowledge_dir()
    
    # Use conversation_id as filename
    filename = f"{conversation_id}.md"
    
    file_path = knowledge_dir / filename
    
    # If file exists, append with separator
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()
        
        # Add separator and new content
        separator = "\n\n---\n\n"
        content = f"{existing_content}{separator}## Update: {datetime.now().isoformat()}\n\n{content}"
    
    # Write content
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return str(file_path)


def read_knowledge(conversation_id: str) -> Optional[str]:
    """Read knowledge from a markdown file by conversation_id.
    
    Args:
        conversation_id: The conversation ID to read ({conversation_id}.md)
        
    Returns:
        File content or None if file doesn't exist
    """
    knowledge_dir = ensure_knowledge_dir()
    filename = f"{conversation_id}.md"
    file_path = knowledge_dir / filename
    
    if not file_path.exists():
        return None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def list_knowledge_files(topic: Optional[str] = None) -> List[str]:
    """List all knowledge markdown files.
    
    Args:
        topic: Optional topic filter (searches in filename)
        
    Returns:
        List of filenames
    """
    knowledge_dir = ensure_knowledge_dir()
    
    if not knowledge_dir.exists():
        return []
    
    files = [f.name for f in knowledge_dir.glob("*.md")]
    
    # Filter by topic if provided
    if topic:
        topic_lower = topic.lower()
        files = [f for f in files if topic_lower in f.lower()]
    
    return sorted(files, reverse=True)  # Most recent first


def search_knowledge(query: str, max_results: int = 5) -> List[dict]:
    """Search knowledge files for content matching a query.
    
    Args:
        query: Search query (searches in file content)
        max_results: Maximum number of results to return
        
    Returns:
        List of dicts with 'filename' and 'content' keys
    """
    knowledge_dir = ensure_knowledge_dir()
    
    if not knowledge_dir.exists():
        return []
    
    results = []
    query_lower = query.lower()
    
    # Search through all markdown files
    for file_path in knowledge_dir.glob("*.md"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Simple text search (could be enhanced with semantic search)
            if query_lower in content.lower():
                results.append({
                    'filename': file_path.name,
                    'content': content[:1000],  # First 1000 chars as preview
                    'path': str(file_path)
                })
                
                if len(results) >= max_results:
                    break
        except (IOError, OSError, UnicodeDecodeError):
            # Skip files that can't be read
            continue
    
    return results


def get_knowledge_summary() -> str:
    """Get a summary of all knowledge files.
    
    Returns:
        Summary string listing all knowledge files
    """
    files = list_knowledge_files()
    
    if not files:
        return "No knowledge files found."
    
    summary = f"Found {len(files)} knowledge file(s):\n\n"
    for filename in files:
        file_path = ensure_knowledge_dir() / filename
        try:
            # Get file size and modification time
            stat = file_path.stat()
            size_kb = stat.st_size / 1024
            mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            summary += f"- {filename} ({size_kb:.1f} KB, modified: {mod_time})\n"
        except (OSError, ValueError):
            summary += f"- {filename}\n"
    
    return summary

