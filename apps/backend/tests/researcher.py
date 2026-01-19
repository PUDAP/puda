"""Test script for the researcher agent.

This script allows direct testing of the researcher agent without going through the API.
Run with: uv run tests/test_researcher.py (from the backend directory)
Or: python -m tests.test_researcher (from the backend directory)
"""
import sys
from pathlib import Path
from langchain_core.messages import HumanMessage

# Add backend directory to path so we can import app modules
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.agents.researcher.agent2 import researcher_graph

def test_researcher(query: str, thread_id: str = "test-thread-1"):
    """
    Test the researcher agent with a query.
    
    Args:
        query: The research query to test
        thread_id: Thread ID for conversation history (default: "test-thread-1")
    """
    print(f"\n{'='*60}")
    print("Testing Researcher Agent")
    print(f"{'='*60}")
    print(f"Query: {query}")
    print(f"Thread ID: {thread_id}")
    print(f"{'='*60}\n")
    
    # Configure the graph with thread_id
    config = {"configurable": {"thread_id": thread_id}}
    
    # Invoke the graph with the query
    print("Invoking researcher agent...\n")
    result_state = researcher_graph.invoke(
        {"messages": [HumanMessage(content=query)]},
        config=config
    )
    
    # Extract and display results
    messages = result_state.get("messages", [])
    usage_metadata = result_state.get("usage_metadata")
    
    print(f"{'='*60}")
    print("RESULT:")
    print(f"{'='*60}")
    
    if messages:
        # Print all messages in the conversation
        for i, msg in enumerate(messages, 1):
            msg_type = type(msg).__name__
            print(f"\n[{i}] {msg_type}:")
            if hasattr(msg, 'content'):
                print(f"Content: {msg.content}")
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                print(f"Tool Calls: {len(msg.tool_calls)}")
                for tool_call in msg.tool_calls:
                    print(f"  - {tool_call.get('name', 'unknown')}: {tool_call.get('args', {})}")
            print()
    else:
        print("No messages in result")
    
    # Display usage metadata if available
    if usage_metadata:
        print(f"{'='*60}")
        print("USAGE METADATA:")
        print(f"{'='*60}")
        print(f"Prompt tokens: {usage_metadata.get('prompt_tokens', 'N/A')}")
        print(f"Completion tokens: {usage_metadata.get('completion_tokens', 'N/A')}")
        print(f"Total tokens: {usage_metadata.get('total_tokens', 'N/A')}")
    
    # Extract final result
    if messages:
        last_message = messages[-1]
        if hasattr(last_message, 'content') and last_message.content:
            print(f"\n{'='*60}")
            print("FINAL RESPONSE:")
            print(f"{'='*60}")
            print(last_message.content)
            print()
    
    return result_state


if __name__ == "__main__":
    # Example test queries
    test_queries = [
        "What is the latest research on CRISPR gene editing?",
        "Compare the tools, nats mqtt and gprc",
    ]
    
    # Test with the first query
    test_researcher(
        query=test_queries[1],
        thread_id="test-researcher-1"
    )