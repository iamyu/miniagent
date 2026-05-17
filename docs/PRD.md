# MiniAgent - Product Requirements Document (PRD)

## Document Information

| Field | Value |
|-------|-------|
| **Product Name** | MiniAgent |
| **Version** | 1.1.0 |
| **Document Version** | 1.0 |
| **Last Updated** | 2026-05-17 |
| **Status** | Released |
| **Author** | MiniAgent Development Team |

---

## 1. Executive Summary

### 1.1 Product Overview

MiniAgent is a lightweight, extensible AI Agent framework that enables developers and users to interact with large language models (Qwen via DashScope) through an intuitive interface. The system combines conversational AI with a powerful plugin architecture for skills and tools, allowing users to automate complex tasks, manage files, execute code, and search the web—all through natural language commands.

### 1.2 Vision Statement

To democratize AI agent development by providing a simple, flexible, and powerful framework that requires minimal setup while offering maximum extensibility through a skill-based plugin system.

### 1.3 Target Audience

- **Primary Users**: Developers, AI enthusiasts, power users who need customizable AI assistants
- **Secondary Users**: Teams requiring task automation, researchers exploring AI agent architectures
- **Technical Level**: Intermediate (requires basic Python knowledge for advanced customization)

### 1.4 Key Value Propositions

1. **Simplicity**: Zero-code skill integration through Markdown files with YAML frontmatter
2. **Flexibility**: Plugin-based architecture allows unlimited extensibility
3. **Power**: Full access to file system, shell commands, web operations, and script execution
4. **Dual Interface**: Both CLI and modern Web UI for different use cases
5. **Lightweight**: Minimal dependencies, fast startup, low resource consumption

---

## 2. Problem Statement

### 2.1 Current Challenges

1. **Complexity of AI Agent Development**: Existing frameworks require significant boilerplate code and complex configuration
2. **Limited Extensibility**: Most chatbots lack easy mechanisms for adding custom capabilities
3. **High Barrier to Entry**: Setting up AI agents often requires deep technical knowledge
4. **Rigid Architectures**: Traditional systems don't support dynamic skill loading based on context
5. **Lack of Tool Integration**: Many AI chat interfaces cannot perform real-world actions (file operations, code execution, etc.)

### 2.2 Solution

MiniAgent addresses these challenges by:
- Providing a configuration-driven approach with sensible defaults
- Implementing a keyword-triggered skill system that automatically activates relevant capabilities
- Offering comprehensive tool support for real-world task execution
- Supporting both command-line and web-based interfaces
- Using standard formats (Markdown + YAML) for skill definition

---

## 3. Product Features

### 3.1 Core Features

#### 3.1.1 AI Chat Engine
**Description**: Intelligent conversation system powered by Qwen models via DashScope API

**Capabilities**:
- Natural language understanding and generation
- Multi-turn conversation with context management
- Streaming responses for real-time feedback
- Configurable model parameters (temperature, max tokens)
- History management with automatic trimming

**Technical Details**:
- Uses OpenAI-compatible API for flexibility
- Supports streaming and non-streaming modes
- Maintains conversation history (configurable, default 20 turns)
- Error handling with graceful degradation

**User Benefits**:
- Seamless conversational experience
- Context-aware responses
- Customizable behavior through configuration

---

#### 3.1.2 Skill System
**Description**: Plugin architecture for extending agent capabilities through Markdown-based skill definitions

**Architecture**:
```
~/.miniagent/skills/
├── skill-name-1/
│   └── SKILL.md
├── skill-name-2/
│   └── SKILL.md
└── ...
```

**Skill Structure**:
```markdown
---
description: "Brief description of what this skill does"
triggers:
  - "keyword1"
  - "keyword2"
always: false  # Optional: always active
---

# Skill Content

Detailed instructions, rules, and context for the AI...
```

**Key Features**:
- **YAML Frontmatter**: Metadata including description, triggers, and activation mode
- **Keyword Matching**: Automatic skill activation based on user input keywords
- **Always-Active Skills**: Skills that are permanently loaded (e.g., system rules)
- **Dynamic Loading**: Skills can be added/removed without restarting
- **Hot Reload**: `/reload` command refreshes skills from disk

**Matching Algorithm**:
1. Scan all loaded skills for trigger keywords
2. Score skills by number of matched keywords
3. Sort by relevance (highest score first)
4. Inject top-matching skills into system prompt

**User Benefits**:
- Zero-code skill creation (just write Markdown)
- Context-aware capability activation
- Easy sharing and distribution of skills
- Modular and maintainable architecture

---

#### 3.1.3 Tool System (Function Calling)
**Description**: Comprehensive set of built-in tools for real-world task execution

**Available Tools**:

| Tool Name | Description | Use Cases |
|-----------|-------------|-----------|
| `read_file` | Read text files with pagination | Code review, document analysis |
| `write_file` | Create or overwrite files | Report generation, data export |
| `edit_file` | Partial file editing | Code refactoring, content updates |
| `list_dir` | List directory contents | File exploration, project navigation |
| `shell` | Execute CMD commands | System operations, batch processing |
| `run_node` | Execute Node.js scripts/code | JavaScript automation, build tasks |
| `run_python` | Execute Python scripts/code | Data processing, scripting |
| `web_search` | Search the web (DuckDuckGo) | Research, fact-checking |
| `web_fetch` | Fetch and extract URL content | Web scraping, content aggregation |
| `save_document` | Save generated documents | Persistent storage of outputs |

**Tool Execution Flow**:
1. LLM identifies need for tool usage
2. System calls appropriate tool with parameters
3. Tool executes and returns result
4. Result fed back to LLM for further processing
5. Loop continues until task complete (max 10 rounds)

**Safety Features**:
- Dangerous command blocking (format, del /s, etc.)
- Timeout controls (default 30s, max 300s)
- Output truncation for large results
- Permission error handling

**User Benefits**:
- Real-world task automation
- No manual intervention required
- Comprehensive file and system operations
- Web research capabilities

---

#### 3.1.4 Configuration Management
**Description**: Flexible configuration system with cascading priority

**Configuration Sources** (highest to lowest priority):
1. Project-level `config.json` (command-line specified)
2. User-level `~/.miniagent/config.json`
3. Environment variables (`DASHSCOPE_API_KEY`, etc.)
4. Default values

**Configurable Parameters**:
```json
{
  "model": "qwen-plus",
  "api_key": "sk-xxxxx",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "temperature": 0.7,
  "max_tokens": 4096,
  "max_history": 20,
  "system_prompt": "你是一个有帮助的 AI 助手。",
  "skills_dir": null
}
```

**Environment Variables**:
- `DASHSCOPE_API_KEY`: API authentication key
- `DASHSCOPE_BASE_URL`: Custom API endpoint
- `MINIAGENT_MODEL`: Override default model

**User Benefits**:
- Secure API key management
- Project-specific configurations
- Easy environment switching
- Sensible defaults reduce setup friction

---

### 3.2 User Interfaces

#### 3.2.1 Command-Line Interface (CLI)
**Description**: Terminal-based interactive chat with command support

**Commands**:
- `/clear` - Clear conversation history
- `/skills` - List all available skills
- `/tools` - List all available tools
- `/reload` - Reload skills from disk
- `/use <name>` - Manually activate a specific skill
- `/quit` or `/exit` - Exit the application

**Features**:
- Interactive REPL loop
- One-shot query mode (`-q` flag)
- Real-time skill matching display
- Tool call logging
- Keyboard interrupt handling (Ctrl+C)

**Usage**:
```bash
python main.py                    # Interactive mode
python main.py -q "Your query"    # One-shot mode
python main.py chat -c config.json # Custom config
```

---

#### 3.2.2 Web User Interface
**Description**: Modern, responsive web application with real-time chat

**Technology Stack**:
- Backend: FastAPI with WebSocket support
- Frontend: Vanilla JavaScript, CSS3
- Communication: WebSocket for streaming, REST for metadata

**Features**:
- **Real-time Streaming**: Character-by-character response rendering
- **Live Tool Monitoring**: Visual feedback during tool execution
- **Skill Selection**: Dropdown menu for manual skill activation
- **Multi-view Navigation**: Chat, Skills, Settings panels
- **Responsive Design**: Works on desktop and mobile devices
- **Status Indicators**: Model info, API status, WebSocket connection

**Views**:
1. **Chat View**: Main conversation interface with message history
2. **Skills View**: Grid display of all available skills with descriptions
3. **Settings View**: Configuration editor for model parameters

**WebSocket Message Types**:
- `text`: Streaming text chunks
- `tool_start`: Tool execution beginning
- `tool_end`: Tool execution complete
- `status`: System notifications
- `done`: Response completion
- `error`: Error messages

**Server Endpoints**:
- `GET /` - Serve web UI
- `GET /api/config` - Get current configuration
- `GET /api/tools` - List available tools
- `GET /api/skills` - List available skills
- `POST /api/chat` - Synchronous chat (fallback)
- `POST /api/clear` - Clear history
- `POST /api/reload-skills` - Reload skills
- `WS /api/ws` - WebSocket streaming chat

**Usage**:
```bash
python main.py web              # Start web server (default port 7860)
python main.py web --port 8080  # Custom port
python main.py web --host localhost # Restrict to localhost
```

---

### 3.3 Advanced Features

#### 3.3.1 Runtime Bundling
**Description**: Embedded Node.js and Python runtimes for portable execution

**Structure**:
```
miniagent/
└── runtime/
    ├── node/      # Bundled Node.js runtime
    └── python/    # Bundled Python runtime (future)
```

**Benefits**:
- No external runtime installation required
- Consistent execution environment
- Portable across different systems
- Isolated from system-wide installations

---

#### 3.3.2 Output Directory Management
**Description**: Centralized output directory for all generated files

**Location**: `<miniagent_root>/output/`

**Purpose**:
- Organized file storage
- Easy access to generated documents
- Consistent working directory for tools
- Separation from source code

**Usage in Prompts**:
The system prompt explicitly instructs the AI to save all generated documents to this directory using the `cwd` parameter in tool calls.

---

#### 3.3.3 Conversation History Management
**Description**: Intelligent history tracking with automatic pruning

**Features**:
- Configurable history depth (default: 20 turns)
- Automatic trimming when limit exceeded
- Clean history (excludes tool call artifacts)
- Persistent within session, cleared on restart

**Implementation**:
- Stores only user and assistant messages
- Excludes intermediate tool calls from long-term memory
- Maintains context for coherent multi-turn conversations

---

## 4. Technical Architecture

### 4.1 System Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                  User Interface                  │
│  ┌──────────────┐       ┌──────────────────┐   │
│  │   CLI        │       │   Web UI         │   │
│  │  (cli.py)    │       │  (web.py + HTML) │   │
│  └──────┬───────┘       └────────┬─────────┘   │
└─────────┼────────────────────────┼─────────────┘
          │                        │
          └────────────┬───────────┘
                       │
          ┌────────────▼───────────┐
          │    Chat Engine         │
          │    (chat.py)           │
          │                        │
          │  • Build System Prompt │
          │  • Manage History      │
          │  • Call LLM API        │
          │  • Handle Tool Calls   │
          └────┬───────┬───────┬───┘
               │       │       │
     ┌─────────▼─┐ ┌───▼────┐ ┌▼──────────┐
     │ Skills    │ │ Tools  │ │ Config    │
     │ Loader    │ │Registry│ │ Manager   │
     │(skills.py)│ │(tools. │ │(config.py)│
     │           │ │ py)    │ │           │
     └───────────┘ └────────┘ └───────────┘
          │              │
     ┌────▼──────┐  ┌────▼────────┐
     │ Skill     │  │ Built-in    │
     │ Files     │  │ Tools       │
     │(SKILL.md) │  │             │
     └───────────┘  └─────────────┘
                       │
          ┌────────────▼───────────┐
          │  External Services     │
          │  • DashScope API       │
          │  • DuckDuckGo Search   │
          │  • File System         │
          │  • Shell Commands      │
          └────────────────────────┘
```

### 4.2 Component Breakdown

#### 4.2.1 Core Modules

| Module | File | Responsibility |
|--------|------|----------------|
| Entry Point | `main.py` | Application bootstrap |
| CLI Handler | `cli.py` | Command parsing, interactive loop |
| Chat Engine | `chat.py` | Conversation logic, LLM integration |
| Skills System | `skills.py` | Skill loading, matching, injection |
| Tools Registry | `tools.py` | Tool definitions, execution |
| Configuration | `config.py` | Config loading, cascading priorities |
| Web Server | `web.py` | FastAPI backend, WebSocket handling |

#### 4.2.2 Data Flow

**Chat Request Flow**:
1. User input received (CLI or Web UI)
2. Input parsed for commands (starts with `/`)
3. If normal message:
   - Skills matched based on keywords
   - System prompt built with active skills
   - Messages array constructed (system + history + user)
   - LLM API called with tools schema
4. If tool call requested:
   - Tool executed with provided parameters
   - Result appended to messages
   - LLM called again with updated context
   - Repeat until no more tool calls (max 10 rounds)
5. Final response returned to user
6. History updated (clean version)

**Skill Loading Flow**:
1. Scan `skills_dir` for subdirectories
2. For each directory, check for `SKILL.md`
3. Parse YAML frontmatter for metadata
4. Create `Skill` object with content and metadata
5. Cache in memory for fast access
6. On match request:
   - Check `always` flag
   - Compare triggers against user input (case-insensitive)
   - Score and sort by match count
   - Return ordered list

---

### 4.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | Python 3.8+ | Core implementation |
| **LLM API** | OpenAI SDK | DashScope integration |
| **Web Framework** | FastAPI | REST API + WebSocket |
| **Frontend** | HTML5, CSS3, Vanilla JS | Web UI |
| **Configuration** | JSON, YAML | Settings and skill metadata |
| **Search** | DuckDuckGo Search API | Web search functionality |
| **Runtime** | Node.js (bundled) | JavaScript execution |

### 4.4 Dependencies

**Python Packages**:
```
openai >= 1.0.0
pyyaml >= 6.0
fastapi >= 0.100.0
uvicorn >= 0.20.0
duckduckgo-search >= 4.0.0  # Optional, for web_search tool
```

**System Requirements**:
- Python 3.8 or higher
- Internet connection (for API calls)
- Disk space for skills and output files

---

## 5. User Stories & Use Cases

### 5.1 Primary User Personas

#### Persona 1: Developer Dave
- **Profile**: Software developer, 28 years old
- **Goals**: Automate repetitive coding tasks, generate documentation
- **Pain Points**: Spending too much time on boilerplate code
- **Use Cases**:
  - Generate Python scripts for data processing
  - Create HTML/CSS templates
  - Refactor existing code
  - Write unit tests

#### Persona 2: Researcher Rachel
- **Profile**: Academic researcher, 35 years old
- **Goals**: Gather information, analyze data, write papers
- **Pain Points**: Manual web research is time-consuming
- **Use Cases**:
  - Search for recent studies on specific topics
  - Fetch and summarize web articles
  - Generate literature review outlines
  - Format citations

#### Persona 3: Power User Pete
- **Profile**: Tech enthusiast, 42 years old
- **Goals**: Customize AI behavior, build personal automation workflows
- **Pain Points**: Existing chatbots are too rigid
- **Use Cases**:
  - Create custom skills for specific domains
  - Batch process files
  - Automate daily reports
  - Integrate with other tools

---

### 5.2 Key Use Cases

#### UC-1: Interactive Coding Assistant
**Actor**: Developer  
**Goal**: Generate and execute code  
**Steps**:
1. User asks: "Create a Python script to scrape product prices from a website"
2. System matches relevant coding skills
3. LLM generates Python code
4. LLM calls `write_file` to save script
5. LLM calls `run_python` to test execution
6. Results displayed to user
**Success Criteria**: Script runs successfully, produces expected output

---

#### UC-2: Automated Research Report
**Actor**: Researcher  
**Goal**: Compile information from multiple sources  
**Steps**:
1. User asks: "Research the latest trends in renewable energy 2024"
2. System calls `web_search` multiple times with different queries
3. For each result, calls `web_fetch` to get full content
4. Synthesizes information into structured report
5. Calls `write_file` to save as Markdown
6. Provides summary to user
**Success Criteria**: Comprehensive report with cited sources, saved to file

---

#### UC-3: Custom Skill Creation
**Actor**: Power User  
**Goal**: Add domain-specific knowledge  
**Steps**:
1. User creates directory: `~/.miniagent/skills/legal-advisor/`
2. Creates `SKILL.md` with legal terminology and guidelines
3. Defines triggers: ["contract", "legal", "agreement"]
4. Runs `/reload` in chat
5. Tests by asking legal questions
6. System automatically activates skill when keywords detected
**Success Criteria**: Skill loads automatically, provides relevant guidance

---

#### UC-4: Batch File Processing
**Actor**: Developer  
**Goal**: Process multiple files efficiently  
**Steps**:
1. User asks: "Rename all .txt files in ./docs to have date prefix"
2. System calls `list_dir` to see current files
3. Generates shell command with proper syntax
4. Calls `shell` to execute batch rename
5. Calls `list_dir` again to verify changes
6. Reports success to user
**Success Criteria**: All files renamed correctly, verification successful

---

#### UC-5: Web Content Aggregation
**Actor**: Researcher  
**Goal**: Monitor news on specific topic  
**Steps**:
1. User asks: "Find today's news about AI regulations"
2. System calls `web_search` with time-filtered query
3. Fetches top 5 article URLs via `web_fetch`
4. Extracts key points from each
5. Compiles summary with links
6. Saves to `output/news-summary.md`
**Success Criteria**: Relevant, recent articles found and summarized

---

## 6. Functional Requirements

### 6.1 Chat Functionality

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| FR-01 | Support multi-turn conversations with context | Must Have | ✓ Implemented |
| FR-02 | Stream responses in real-time (Web UI) | Must Have | ✓ Implemented |
| FR-03 | Maintain conversation history (configurable depth) | Must Have | ✓ Implemented |
| FR-04 | Clear history on demand | Must Have | ✓ Implemented |
| FR-05 | Support one-shot query mode (CLI) | Should Have | ✓ Implemented |
| FR-06 | Display matched skills before response | Should Have | ✓ Implemented |
| FR-07 | Handle API errors gracefully | Must Have | ✓ Implemented |
| FR-08 | Support custom system prompts | Should Have | ✓ Implemented |

---

### 6.2 Skill Management

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| FR-09 | Load skills from designated directory | Must Have | ✓ Implemented |
| FR-10 | Parse YAML frontmatter metadata | Must Have | ✓ Implemented |
| FR-11 | Match skills by keyword triggers | Must Have | ✓ Implemented |
| FR-12 | Support always-active skills | Must Have | ✓ Implemented |
| FR-13 | List all available skills | Must Have | ✓ Implemented |
| FR-14 | Hot reload skills without restart | Must Have | ✓ Implemented |
| FR-15 | Manually activate specific skills | Should Have | ✓ Implemented |
| FR-16 | Display skill descriptions and triggers | Should Have | ✓ Implemented |
| FR-17 | Auto-discover new skills on reload | Must Have | ✓ Implemented |

---

### 6.3 Tool Execution

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| FR-18 | Execute file read/write/edit operations | Must Have | ✓ Implemented |
| FR-19 | List directory contents (recursive option) | Must Have | ✓ Implemented |
| FR-20 | Execute shell commands with timeout | Must Have | ✓ Implemented |
| FR-21 | Run Node.js scripts and inline code | Must Have | ✓ Implemented |
| FR-22 | Run Python scripts and inline code | Must Have | ✓ Implemented |
| FR-23 | Perform web searches | Should Have | ✓ Implemented |
| FR-24 | Fetch and extract web page content | Should Have | ✓ Implemented |
| FR-25 | Block dangerous commands | Must Have | ✓ Implemented |
| FR-26 | Limit tool call loops (max 10 rounds) | Must Have | ✓ Implemented |
| FR-27 | Truncate large outputs | Should Have | ✓ Implemented |
| FR-28 | Log tool calls for transparency | Should Have | ✓ Implemented |

---

### 6.4 Configuration

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| FR-29 | Load config from JSON file | Must Have | ✓ Implemented |
| FR-30 | Support environment variable overrides | Must Have | ✓ Implemented |
| FR-31 | Cascading priority (project > user > env > default) | Must Have | ✓ Implemented |
| FR-32 | Configure model parameters | Must Have | ✓ Implemented |
| FR-33 | Set custom API endpoints | Should Have | ✓ Implemented |
| FR-34 | Specify custom skills directory | Should Have | ✓ Implemented |
| FR-35 | Secure API key handling | Must Have | ✓ Implemented |

---

### 6.5 User Interface

#### 6.5.1 CLI Requirements

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| FR-36 | Interactive REPL loop | Must Have | ✓ Implemented |
| FR-37 | Display welcome message with system info | Should Have | ✓ Implemented |
| FR-38 | Support slash commands | Must Have | ✓ Implemented |
| FR-39 | Handle keyboard interrupts (Ctrl+C) | Must Have | ✓ Implemented |
| FR-40 | Show tool call progress | Should Have | ✓ Implemented |
| FR-41 | One-shot query mode (-q flag) | Should Have | ✓ Implemented |

---

#### 6.5.2 Web UI Requirements

| ID | Requirement | Priority | Status |
|----|------------|----------|--------|
| FR-42 | Responsive design (desktop + mobile) | Must Have | ✓ Implemented |
| FR-43 | Real-time message streaming via WebSocket | Must Have | ✓ Implemented |
| FR-44 | Display tool execution status | Must Have | ✓ Implemented |
| FR-45 | Skill selection dropdown | Should Have | ✓ Implemented |
| FR-46 | Multiple views (Chat, Skills, Settings) | Should Have | ✓ Implemented |
| FR-47 | Clear chat button | Must Have | ✓ Implemented |
| FR-48 | Show system status (model, API, WS) | Should Have | ✓ Implemented |
| FR-49 | Auto-scroll to latest message | Must Have | ✓ Implemented |
| FR-50 | Support Shift+Enter for newlines | Should Have | ✓ Implemented |

---

## 7. Non-Functional Requirements

### 7.1 Performance

| ID | Requirement | Target |
|----|------------|--------|
| NFR-01 | Application startup time | < 2 seconds |
| NFR-02 | Skill loading time (100 skills) | < 1 second |
| NFR-03 | WebSocket message latency | < 100ms |
| NFR-04 | File read operation (1MB file) | < 500ms |
| NFR-05 | Memory usage (idle) | < 200 MB |
| NFR-06 | Maximum concurrent WebSocket connections | 100 |

---

### 7.2 Security

| ID | Requirement | Implementation |
|----|------------|----------------|
| NFR-07 | API key protection | Environment variables, not hardcoded |
| NFR-08 | Dangerous command blocking | Pattern matching in shell tool |
| NFR-09 | File access restrictions | User-level permissions enforced by OS |
| NFR-10 | Timeout enforcement | Configurable timeouts on all external calls |
| NFR-11 | Input validation | Parameter type checking in all tools |
| NFR-12 | Output sanitization | Truncation of excessively long outputs |

---

### 7.3 Reliability

| ID | Requirement | Target |
|----|------------|--------|
| NFR-13 | API error recovery | Graceful degradation with error messages |
| NFR-14 | Tool execution failure handling | Return error details, continue conversation |
| NFR-15 | WebSocket reconnection | Not implemented (single session) |
| NFR-16 | History persistence | Session-only (cleared on restart) |
| NFR-17 | Skill file corruption handling | Skip invalid files, log warnings |

---

### 7.4 Usability

| ID | Requirement | Standard |
|----|------------|----------|
| NFR-18 | CLI help availability | `--help` flag on all commands |
| NFR-19 | Error message clarity | Human-readable, actionable errors |
| NFR-20 | Command discoverability | List commands in welcome message |
| NFR-21 | Skill documentation | YAML frontmatter with description |
| NFR-22 | Tool documentation | Descriptions in schema |
| NFR-23 | Web UI intuitiveness | Clear labels, icons, tooltips |

---

### 7.5 Maintainability

| ID | Requirement | Approach |
|----|------------|----------|
| NFR-24 | Code modularity | Separate modules for each concern |
| NFR-25 | Configuration flexibility | JSON + environment variables |
| NFR-26 | Skill extensibility | Markdown-based, no code changes needed |
| NFR-27 | Logging | Console output for debugging |
| NFR-28 | Documentation | README + inline comments |

---

## 8. Constraints & Assumptions

### 8.1 Technical Constraints

1. **Model Dependency**: Requires DashScope API access (Qwen models)
2. **Python Version**: Minimum Python 3.8 required
3. **Internet Connection**: Required for API calls and web tools
4. **Single-User**: Designed for single-user sessions (no multi-user support)
5. **No Database**: All state in-memory, no persistent storage except files
6. **Windows-Centric**: Shell tool optimized for Windows CMD (limited cross-platform)

---

### 8.2 Business Constraints

1. **API Costs**: Usage incurs DashScope API charges
2. **Rate Limits**: Subject to DashScope API rate limits
3. **Open Source**: MIT-style license (permissive)
4. **No Commercial Support**: Community-driven project

---

### 8.3 Assumptions

1. Users have basic Python knowledge for advanced customization
2. Skills are trusted (no sandboxing or security isolation)
3. File system access is intentional and user-approved
4. Web search results are used responsibly
5. Users understand risks of executing arbitrary code/commands

---

## 9. Future Enhancements (Roadmap)

### 9.1 Short-Term (v1.2 - Next 3 Months)

- [ ] **Multi-Model Support**: Add support for other LLM providers (OpenAI, Anthropic)
- [ ] **Skill Marketplace**: Centralized repository for sharing skills
- [ ] **Conversation Persistence**: Save/load conversation histories
- [ ] **Enhanced Web UI**: Dark mode, themes, customizable layouts
- [ ] **Tool Composition**: Chain multiple tools in single workflow
- [ ] **Better Error Handling**: Retry logic for transient failures

---

### 9.2 Medium-Term (v2.0 - 6-12 Months)

- [ ] **Multi-User Support**: User accounts, isolated sessions
- [ ] **Skill Versioning**: Track skill changes, rollback capability
- [ ] **Advanced Scheduling**: Cron-like task automation
- [ ] **Plugin System**: Python-based plugins for complex logic
- [ ] **Voice Interface**: Speech-to-text integration
- [ ] **Mobile App**: Native iOS/Android applications
- [ ] **Analytics Dashboard**: Usage statistics, popular skills

---

### 9.3 Long-Term (v3.0 - 12+ Months)

- [ ] **Agent Collaboration**: Multiple agents working together
- [ ] **Learning Mode**: Adapt to user preferences over time
- [ ] **Visual Workflow Builder**: Drag-and-drop task automation
- [ ] **Enterprise Features**: SSO, audit logs, compliance
- [ ] **Skill Certification**: Verified skills from trusted sources
- [ ] **API Gateway**: Expose MiniAgent as REST API service
- [ ] **Containerization**: Docker images for easy deployment

---

## 10. Success Metrics

### 10.1 Adoption Metrics

| Metric | Target (6 months) | Measurement |
|--------|-------------------|-------------|
| GitHub Stars | 500+ | GitHub API |
| Active Users | 100+ monthly | Self-reported |
| Skills Created | 50+ community skills | GitHub repos |
| Downloads | 1,000+ | PyPI stats (if published) |

---

### 10.2 Performance Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Average Response Time | < 3 seconds | Internal logging |
| Tool Success Rate | > 95% | Error tracking |
| Skill Match Accuracy | > 80% relevant | User feedback |
| Uptime (Web Server) | > 99% | Health checks |

---

### 10.3 Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Bug Resolution Time | < 48 hours | Issue tracker |
| User Satisfaction | > 4.0/5.0 | Surveys |
| Documentation Completeness | 100% features documented | Audit |
| Code Coverage | > 70% | Testing tools |

---

## 11. Risk Analysis

### 11.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| API service disruption | Medium | High | Support multiple providers, caching |
| Security vulnerabilities in skills | High | Critical | Sandboxing, skill review process |
| Performance degradation with many skills | Low | Medium | Lazy loading, indexing |
| Breaking changes in dependencies | Medium | Medium | Pin versions, regular updates |
| Cross-platform compatibility issues | Medium | Medium | Extensive testing, CI/CD |

---

### 11.2 Business Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| API cost increases | Medium | High | Cost monitoring, usage limits |
| Competitor products | High | Medium | Focus on simplicity, community |
| Limited adoption | Medium | High | Better marketing, tutorials |
| Regulatory changes (AI) | Low | High | Stay compliant, legal review |

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| **Skill** | A Markdown file with YAML frontmatter that extends agent capabilities |
| **Trigger** | Keywords that automatically activate a skill |
| **Tool** | A function the AI can call to perform actions (file ops, shell commands, etc.) |
| **Function Calling** | OpenAI-compatible mechanism for AI to request tool execution |
| **Frontmatter** | YAML metadata at the top of a Markdown file (between `---` markers) |
| **DashScope** | Alibaba Cloud's platform for accessing Qwen models |
| **Streaming** | Sending response text incrementally as it's generated |
| **Hot Reload** | Refreshing skills from disk without restarting the application |
| **One-Shot Mode** | CLI mode that processes a single query and exits |
| **Always-Active Skill** | A skill that's loaded in every conversation regardless of triggers |

---

## 13. Appendices

### Appendix A: Example Skill

```markdown
---
name: code-reviewer
description: "Reviews code for best practices, bugs, and improvements"
triggers:
  - "review"
  - "check code"
  - "lint"
  - "optimize"
always: false
---

# Code Reviewer Skill

When reviewing code, follow these guidelines:

1. **Check for Common Issues**:
   - Syntax errors
   - Logic bugs
   - Security vulnerabilities (SQL injection, XSS, etc.)
   - Performance bottlenecks

2. **Best Practices**:
   - Follow PEP 8 (Python) or language-specific style guides
   - Use meaningful variable names
   - Add comments for complex logic
   - Keep functions small and focused

3. **Suggestions**:
   - Provide specific, actionable improvements
   - Explain why changes are recommended
   - Include code examples when helpful
   - Prioritize suggestions by impact

4. **Tone**:
   - Be constructive, not critical
   - Acknowledge good practices
   - Offer alternatives, not just corrections

Example response format:
- ✅ Good: [what's done well]
- ⚠️ Consider: [suggestion with explanation]
- ❌ Fix: [critical issue requiring attention]
```

---

### Appendix B: API Schema Reference

**Chat Completion Request**:
```json
{
  "model": "qwen-plus",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "tools": [...],
  "temperature": 0.7,
  "max_tokens": 4096,
  "stream": true
}
```

**Tool Definition Schema**:
```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a text file...",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string"}
      },
      "required": ["path"]
    }
  }
}
```

---

### Appendix C: Configuration Examples

**Minimal Config**:
```json
{
  "api_key": "sk-your-key-here"
}
```

**Full Config**:
```json
{
  "model": "qwen-plus",
  "api_key": "sk-your-key-here",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "temperature": 0.7,
  "max_tokens": 4096,
  "max_history": 20,
  "system_prompt": "You are a helpful AI assistant.",
  "skills_dir": "/custom/path/to/skills"
}
```

**Environment Variables**:
```bash
export DASHSCOPE_API_KEY="sk-your-key-here"
export MINIAGENT_MODEL="qwen-max"
```

---

### Appendix D: Troubleshooting Guide

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| "No API key configured" | Missing API key | Set in config.json or environment variable |
| "Connection refused" | Network/firewall | Check internet, proxy settings |
| "Skill not found" | Wrong name or path | Verify skill exists in skills_dir |
| "Tool execution failed" | Permission denied | Check file permissions, admin rights |
| "Timeout expired" | Long-running command | Increase timeout parameter |
| "WebSocket disconnected" | Network instability | Refresh page, check connection |
| "Command blocked for safety" | Dangerous pattern detected | Run manually in terminal if needed |

---

## 14. Document Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-05-17 | MiniAgent Team | Initial PRD creation |

---

**End of Document**
