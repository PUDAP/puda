# Knowledge Agent

The Knowledge Agent is designed to review conversations between users and agents, extract important information, and save it to markdown files for future context retrieval.

## Purpose

Communication between users and agents can be complex, and important context can be lost across conversations. The Knowledge Agent addresses this by:

1. **Reviewing Conversations**: Analyzes conversations to identify key information, decisions, configurations, and learnings
2. **Extracting Knowledge**: Uses LLM to intelligently extract and structure important information
3. **Saving to Markdown**: Stores knowledge in well-organized markdown files for easy retrieval
4. **Context Retrieval**: Enables other agents to retrieve relevant knowledge when needed

## Architecture

### Components

- **`state.py`**: Defines the `KnowledgeState` TypedDict with fields for conversation tracking, extracted knowledge, and file paths
- **`nodes.py`**: Contains node functions:
  - `review_conversation_node`: Analyzes conversations and extracts knowledge using LLM
  - `save_knowledge_node`: Saves extracted knowledge to markdown files
  - `retrieve_knowledge_node`: Searches and retrieves relevant knowledge
  - `knowledge_review_and_save_node`: Combined node for convenience
- **`tools.py`**: File I/O utilities:
  - `save_knowledge()`: Save knowledge to markdown files
  - `read_knowledge()`: Read knowledge from files
  - `list_knowledge_files()`: List all knowledge files
  - `search_knowledge()`: Search knowledge files by content
  - `get_knowledge_summary()`: Get summary of all knowledge files
- **`agent.py`**: Defines and compiles the LangGraph workflow

### Knowledge Storage

Knowledge files are stored in `apps/backend/knowledge/` directory. Files are organized by conversation_id:
- Each conversation has a single file: `{conversation_id}.md`
- All knowledge for a conversation is accumulated in that file
- This enables easy context sharing between agents for the same conversation

## Usage

### API Endpoints

#### Review and Save Knowledge

```bash
POST /v1/agents/knowledge/review
```

Request body:
```json
{
  "query": "Review this conversation and save important knowledge",
  "conversation_id": "optional-id",
  "message_history": [/* BaseMessage instances */],
  "model_name": "optional-model",
  "verbose": false
}
```

This endpoint:
1. Reviews the provided conversation (or message_history)
2. Extracts important knowledge using LLM
3. Saves knowledge to a markdown file
4. Returns the file path and extracted knowledge

#### Retrieve Knowledge

```bash
POST /v1/agents/knowledge/retrieve
```

Request body:
```json
{
  "query": "search term or topic",
  "model_name": "optional-model",
  "verbose": false
}
```

This endpoint searches knowledge files and returns relevant content.

### Integration with Other Agents

The Knowledge Agent is integrated into the general workflow router. It can be triggered by:
- Explicit requests: "save knowledge", "review conversation", "extract knowledge"
- Automatic invocation: Can be called after other agents complete their tasks
- Programmatic access: Other agents can call knowledge tools directly

### Example Workflow

1. User has a conversation with the researcher agent about machine configurations
   - Conversation ID: `abc-123-def`
2. After the conversation, call the knowledge agent to review and save:
   ```python
   POST /v1/agents/knowledge/review
   {
     "conversation_id": "abc-123-def",
     "message_history": [/* conversation messages */]
   }
   ```
3. Knowledge agent extracts important information (configurations, decisions, etc.)
4. Knowledge is saved to `knowledge/abc-123-def.md`
5. Later, retrieve the knowledge for the same conversation:
   ```python
   POST /v1/agents/knowledge/retrieve
   {
     "conversation_id": "abc-123-def"
   }
   ```
   Or search across all conversations:
   ```python
   POST /v1/agents/knowledge/retrieve
   {
     "query": "machine configuration"
   }
   ```

## Knowledge File Format

Knowledge files are markdown formatted with:
- Clear headings and sections
- Relevant details and context
- Updates appended with separators and timestamps
- All knowledge for a conversation accumulates in one file

Example (`abc-123-def.md`):
```markdown
# Machine Configuration Knowledge

## First Machine Setup
- Default pipette: 300μL
- Deck layout: Standard 96-well plate
- Safety limits: X-axis ±200mm

## User Preferences
- Preferred protocol format: Opentrons API v2
- Common labware: 96-well plates, tip racks

---
## Update: 2024-12-01T12:30:00

Additional configuration notes from later in the conversation...
```

## Future Enhancements

- Semantic search using embeddings
- Automatic knowledge extraction after agent interactions
- Knowledge graph construction
- Cross-referencing between knowledge files
- Version control for knowledge updates
- Integration with vector databases for better retrieval

