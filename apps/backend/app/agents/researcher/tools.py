"""Tools for the researcher agent to perform web searches and research."""
import json
import sys
from pathlib import Path
from typing import List
from langchain_core.tools import tool
from langsmith import traceable
from ddgs import DDGS

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


@tool("ddg_search", description="Search the web using DuckDuckGo to find current information, articles, research papers, or any web content. Use this when you need to find up-to-date information, verify facts, or gather information from the internet. The query should be a clear search term or question.")
@traceable(name="ddg_search")
def ddg_search(query: str, max_results: int = 5) -> str:
    """Perform a web search using DuckDuckGo.
    
    Args:
        query: The search query or question to search for
        max_results: Maximum number of results to return (default: 5)
        
    Returns:
        A formatted string containing search results with titles, URLs, and snippets
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            
            if not results:
                return json.dumps({"error": f"No results found for query: {query}"})
            
            structured_results = []
            for result in results:
                structured_results.append({
                    "title": result.get('title', 'No title'),
                    "url": result.get('href', 'No URL'),
                    "description": result.get('body', 'No description available')
                })
            
            return json.dumps({"results": structured_results})
    except Exception as e:  # noqa: BLE001
        # Catch all exceptions from web search API to prevent agent failure
        return json.dumps({"error": f"Error performing web search: {str(e)}"})


def get_researcher_tools() -> List:
    """Get all tools available to the researcher agent.
    
    Returns:
        List of LangChain tools for the researcher agent
    """
    return [
        ddg_search,
    ]

