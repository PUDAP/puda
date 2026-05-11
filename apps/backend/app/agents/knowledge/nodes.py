"""Node functions for the knowledge agent graph."""
import sys
from os import getenv
from dotenv import load_dotenv
from pathlib import Path
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.agents.knowledge.state import KnowledgeState, KNOWLEDGE_AGENT_INSTRUCTIONS
from app.agents.knowledge.tools import (
    save_knowledge,
    read_knowledge,
    list_knowledge_files,
    search_knowledge,
    get_knowledge_summary
)
from langchain.chat_models import init_chat_model

load_dotenv()

# Add backend directory to path when loaded directly by LangGraph
_backend_root = Path(__file__).parent.parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def review_conversation_node(state: KnowledgeState) -> KnowledgeState:
    """Review a conversation and extract important knowledge.
    
    This node analyzes the conversation and uses an LLM to extract
    important information that should be saved for future reference.
    """
    # Get conversation to review (either from state or messages)
    conversation = state.get("conversation_to_review") or state.get("messages", [])
    
    if not conversation:
        return {
            **state,
            "extracted_knowledge": "No conversation to review.",
        }
    
    # Use LangChain chat model
    model_name = state.get("model_name") or "openai/gpt-4o-mini"
    knowledge_model = init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=getenv("OPENAI_API_KEY"),
        temperature=0.3,  # Lower temperature for more consistent extraction
    )
    
    # Convert conversation to text for analysis
    conversation_text = []
    for msg in conversation:
        if isinstance(msg, SystemMessage):
            conversation_text.append(f"System: {msg.content}")
        elif isinstance(msg, HumanMessage):
            conversation_text.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            conversation_text.append(f"Assistant: {msg.content}")
        else:
            content = msg.content if hasattr(msg, 'content') else str(msg)
            conversation_text.append(f"Unknown: {content}")
    
    conversation_str = "\n".join(conversation_text)
    
    # Prepare prompt for knowledge extraction
    extraction_prompt = f"""Review the following conversation and extract important knowledge that should be saved for future reference.

Focus on:
- Key decisions and their rationale
- Important configurations or settings
- User preferences and patterns
- Solutions to problems encountered
- Important context or background information
- Reusable knowledge for similar future tasks

Format the extracted knowledge as a well-structured markdown document with:
- Clear headings and sections
- Relevant details and context
- Tags or categories for organization
- Timestamps if relevant

Conversation:
{conversation_str}

Extract and format the knowledge:"""

    # Prepare messages for LangChain
    extraction_messages = [
        SystemMessage(content=KNOWLEDGE_AGENT_INSTRUCTIONS),
        HumanMessage(content=extraction_prompt)
    ]
    
    # Call LLM to extract knowledge
    response = knowledge_model.invoke(extraction_messages)
    
    extracted_knowledge = response.content if hasattr(response, 'content') else str(response)
    
    # Extract usage metadata from LangChain response
    usage_metadata = None
    if hasattr(response, 'response_metadata'):
        metadata = response.response_metadata
        if metadata and 'token_usage' in metadata:
            token_usage = metadata['token_usage']
            usage_metadata = {
                'prompt_tokens': token_usage.get('prompt_tokens', 0),
                'completion_tokens': token_usage.get('completion_tokens', 0),
                'total_tokens': token_usage.get('total_tokens', 0),
            }
    
    return {
        **state,
        "extracted_knowledge": extracted_knowledge,
        "usage_metadata": usage_metadata
    }


def save_knowledge_node(state: KnowledgeState) -> KnowledgeState:
    """Save extracted knowledge to a markdown file organized by conversation_id.
    
    This node takes the extracted knowledge and saves it to a file
    named {conversation_id}.md.
    """
    extracted_knowledge = state.get("extracted_knowledge")
    conversation_id = state.get("conversation_id")
    
    if not extracted_knowledge or extracted_knowledge == "No knowledge extracted":
        return {
            **state,
            "knowledge_file_path": None
        }
    
    if not conversation_id:
        return {
            **state,
            "knowledge_file_path": None
        }
    
    # Save knowledge using conversation_id
    file_path = save_knowledge(
        content=extracted_knowledge,
        conversation_id=conversation_id
    )
    
    return {
        **state,
        "knowledge_file_path": file_path
    }


def retrieve_knowledge_node(state: KnowledgeState) -> KnowledgeState:
    """Retrieve relevant knowledge based on conversation_id or query.
    
    If conversation_id is provided, reads that specific file.
    Otherwise, searches for knowledge matching the query.
    """
    conversation_id = state.get("conversation_id")
    query = state.get("retrieval_query")
    
    # If conversation_id is provided, read that specific file
    if conversation_id:
        knowledge_content = read_knowledge(conversation_id)
        if knowledge_content:
            return {
                **state,
                "retrieved_knowledge": knowledge_content
            }
        else:
            return {
                **state,
                "retrieved_knowledge": f"No knowledge file found for conversation_id: {conversation_id}"
            }
    
    # Otherwise, search by query
    if not query:
        return {
            **state,
            "retrieved_knowledge": "No conversation_id or retrieval query provided."
        }
    
    # Search for relevant knowledge
    search_results = search_knowledge(query, max_results=3)
    
    if not search_results:
        return {
            **state,
            "retrieved_knowledge": f"No knowledge found matching query: {query}"
        }
    
    # Format results
    retrieved_content = f"Found {len(search_results)} relevant knowledge file(s) for query: {query}\n\n"
    for result in search_results:
        retrieved_content += f"## {result['filename']}\n\n"
        retrieved_content += f"{result['content']}\n\n"
        retrieved_content += f"*Path: {result['path']}*\n\n---\n\n"
    
    return {
        **state,
        "retrieved_knowledge": retrieved_content
    }


def knowledge_review_and_save_node(state: KnowledgeState) -> KnowledgeState:
    """Combined node that reviews conversation and saves knowledge.
    
    This is a convenience node that combines review and save operations.
    """
    # First review the conversation
    state_after_review = review_conversation_node(state)
    
    # Then save the knowledge
    state_after_save = save_knowledge_node(state_after_review)
    
    return state_after_save

