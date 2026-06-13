// ============ MiniAgent Web Client — local-agent style ============

const state = {
    currentView: 'chat',
    skills: [],
    tools: [],
    config: {},
    isStreaming: false,
    skillsDropdownVisible: false,
    ws: null,
    wsConnected: false,
    currentAssistant: null,  // { content, tools[] }
    currentSessionId: null,  // current session ID from server
    wsReconnectAttempts: 0,  // track reconnection attempts
    wsMaxReconnectDelay: 30000,  // max 30s between retries
};

const API_BASE = '';

// ============ Init ============
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    await loadSkills();
    initEventListeners();
    connectWS();
});

// ============ WebSocket ============
function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/api/ws`;

    // Close existing connection if any
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
        state.ws.onclose = null;  // prevent re-entry
        state.ws.close();
    }

    state.ws = new WebSocket(url);

    state.ws.onopen = () => {
        state.wsConnected = true;
        state.wsReconnectAttempts = 0;  // reset on successful connect
        updateWSStatus('connected');
    };

    state.ws.onclose = () => {
        state.wsConnected = false;
        updateWSStatus('disconnected');
        // Exponential backoff: 1s, 2s, 4s, 8s... up to 30s
        const delay = Math.min(1000 * Math.pow(2, state.wsReconnectAttempts), state.wsMaxReconnectDelay);
        state.wsReconnectAttempts++;
        console.log(`[WS] Disconnected, reconnecting in ${delay}ms (attempt ${state.wsReconnectAttempts})`);
        setTimeout(connectWS, delay);
    };

    state.ws.onerror = (e) => {
        // Don't update status here — onclose will fire right after
        console.error('[WS] Error:', e);
    };

    state.ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg);
        } catch (e) {
            console.error('WS message parse error:', e);
        }
    };
}

function sendWS(data) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(data));
    }
}

function updateWSStatus(status) {
    const el = document.getElementById('info-ws');
    if (el) {
        el.textContent = status === 'connected' ? 'Connected' : 'Disconnected';
        el.className = 'info-value ' + status;
    }
}

function handleWSMessage(msg) {
    const type = msg.type;

    if (type === 'text') {
        if (!state.currentAssistant) {
            state.currentAssistant = { content: '', tools: [] };
            appendAssistantBubble();
        }
        state.currentAssistant.content += msg.content;
        updateAssistantBubble(state.currentAssistant.content);
    }
    else if (type === 'tool_start') {
        if (!state.currentAssistant) {
            state.currentAssistant = { content: '', tools: [] };
            appendAssistantBubble();
        }
        const toolEntry = {
            name: msg.name, args: msg.args,
            result: null, done: false, truncated: false
        };
        state.currentAssistant.tools.push(toolEntry);
        // Always use last position in accumulated array (backend index resets each round)
        const cardIdx = state.currentAssistant.tools.length - 1;
        console.debug(`[tool_start] name=${msg.name}, index=${cardIdx}, args_type=${typeof msg.args}`);
        appendToolCard(msg.name, msg.args, cardIdx);
        showProcessing('模型正在生成参数: ' + msg.name + '...');
    }
    else if (type === 'tool_args') {
        // Stream raw tool call arguments into the tool card in real-time
        // Use last non-done tool with matching name (backend index resets per round)
        const tools = state.currentAssistant?.tools;
        let idx = tools ? tools.length - 1 : 0;
        if (tools && msg.name) {
            for (let i = tools.length - 1; i >= 0; i--) {
                if (tools[i].name === msg.name && !tools[i].done) { idx = i; break; }
            }
        }
        appendToolCardArgs(idx, msg.content);
    }
    else if (type === 'tool_end') {
        const tools = state.currentAssistant?.tools;
        // Find the last not-done tool with matching name (backend index resets per round)
        let idx = -1;
        if (tools) {
            for (let i = tools.length - 1; i >= 0; i--) {
                if (tools[i].name === msg.name && !tools[i].done) {
                    idx = i;
                    break;
                }
            }
        }
        if (idx < 0 && tools && tools.length > 0) {
            idx = tools.length - 1;  // fallback
        }
        if (tools && idx >= 0 && idx < tools.length) {
            const tool = tools[idx];
            tool.result = msg.result;
            tool.truncated = msg.truncated;
            tool.done = true;
            updateToolCard(tool, idx);
        }
        // Show completed tools count
        const doneCount = state.currentAssistant?.tools.filter(t => t.done).length || 0;
        const totalCount = state.currentAssistant?.tools.length || 0;
        showProcessing('已完成 ' + doneCount + '/' + totalCount + ' 个工具, 生成回答中...');
    }
    else if (type === 'done') {
        // Show tool completion summary as a system message
        const toolCount = state.currentAssistant?.tools?.length || 0;
        if (toolCount > 0) {
            const doneCount = state.currentAssistant.tools.filter(t => t.done).length;
            appendSystemMessage('✓ 工具执行完成 (' + doneCount + '/' + toolCount + ')');
        }
        finalizeAssistantMessage();
    }
    else if (type === 'error') {
        finalizeAssistantMessage();
        appendSystemMessage(msg.content);
        hideProcessing();
    }
    else if (type === 'system') {
        appendSystemMessage(msg.content);
    }
    else if (type === 'status') {
        appendSystemMessage(msg.content);
    }
    else if (type === 'processing') {
        // Update the processing indicator text (no new message, just update status line)
        showProcessing(msg.content);
    }
}

// ============ Events ============
function initEventListeners() {
    // Navigation - skip new-chat-btn, it has its own handler
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            if (item.id === 'new-chat-btn') return;  // handled separately
            switchView(item.dataset.view);
        });
    });

    // New chat button - creates a new session
    const newChatBtn = document.getElementById('new-chat-btn');
    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => newSession());
    }

    // Feature cards
    document.querySelectorAll('.feature-card').forEach(card => {
        card.addEventListener('click', () => {
            const action = card.dataset.action;
            if (action === 'ai') switchView('chat');
            else if (action === 'skills') switchView('skills');
            else if (action === 'file') {
                switchView('chat');
                document.getElementById('chat-input').value = '读取当前目录的文件列表';
                document.getElementById('chat-input').focus();
            }
            else if (action === 'code') {
                switchView('chat');
                document.getElementById('chat-input').value = '用 Python 写一个 Hello World';
                document.getElementById('chat-input').focus();
            }
        });
    });

    // Chat input
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
        sendBtn.disabled = !chatInput.value.trim() || state.isStreaming;
    });

    sendBtn.addEventListener('click', sendMessage);

    // Clear
    document.getElementById('clear-chat').addEventListener('click', clearChat);

    // Save settings
    const saveSettingsBtn = document.getElementById('btn-save-settings');
    if (saveSettingsBtn) saveSettingsBtn.addEventListener('click', saveSettings);

    // Skills dropdown
    document.getElementById('skills-toggle-btn').addEventListener('click', toggleSkillsDropdown);
    document.addEventListener('click', (e) => {
        const dd = document.getElementById('skills-dropdown');
        const btn = document.getElementById('skills-toggle-btn');
        if (dd && !dd.contains(e.target) && btn && !btn.contains(e.target)) {
            closeSkillsDropdown();
        }
    });

    // Initialize history
    initHistoryRefresh();
}

// ============ View Switch ============
function switchView(viewName) {
    state.currentView = viewName;
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewName);
    });
    document.querySelectorAll('.view-container').forEach(view => {
        view.classList.toggle('active', view.id === `view-${viewName}`);
    });
    if (viewName === 'skills') loadSkills();
}

// ============ Load Data ============
async function loadConfig() {
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        state.config = await res.json();
        document.getElementById('info-model').textContent = state.config.model || '-';
        document.getElementById('info-api').textContent = state.config.has_api_key ? 'Connected' : 'No Key';
        document.getElementById('info-api').className = 'info-value ' + (state.config.has_api_key ? 'connected' : 'disconnected');

        // Fill settings form
        const modelInput = document.getElementById('setting-model');
        const baseUrlInput = document.getElementById('setting-base-url');
        const tempInput = document.getElementById('setting-temperature');
        const maxTokensInput = document.getElementById('setting-max-tokens');
        if (modelInput) modelInput.value = state.config.model || '';
        if (baseUrlInput) baseUrlInput.value = state.config.base_url || '';
        if (tempInput) tempInput.value = state.config.temperature || 0.7;
        if (maxTokensInput) maxTokensInput.value = state.config.max_tokens || 8192;
    } catch (e) {
        console.error('Failed to load config:', e);
    }
}

async function saveSettings() {
    const btn = document.getElementById('btn-save-settings');
    const originalText = btn.textContent;
    btn.textContent = '保存中...';
    btn.disabled = true;

    try {
        const payload = {
            model: document.getElementById('setting-model')?.value || undefined,
            base_url: document.getElementById('setting-base-url')?.value || undefined,
            temperature: document.getElementById('setting-temperature')?.value || undefined,
            max_tokens: document.getElementById('setting-max-tokens')?.value || undefined,
        };
        // Remove empty values to avoid overwriting with blanks
        Object.keys(payload).forEach(k => { if (payload[k] === undefined || payload[k] === '') delete payload[k]; });

        const res = await fetch(`${API_BASE}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.ok) {
            btn.textContent = '✓ 已保存';
            btn.classList.add('saved');
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('saved');
            }, 2000);
            // Reload config into state
            await loadConfig();
        } else {
            btn.textContent = '保存失败';
            alert('保存失败: ' + (data.error || '未知错误'));
            setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
        }
    } catch (e) {
        btn.textContent = '网络错误';
        console.error('Save settings failed:', e);
        setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
    }
}

function renderSkillsSidebar() {
    const container = document.getElementById('skills-sidebar');
    if (!container) return;  // element doesn't exist in current layout
    if (!state.skills || state.skills.length === 0) {
        container.innerHTML = '<div class="sidebar-info-item">暂无 Skills</div>';
        return;
    }
    container.innerHTML = state.skills.map(s => `
        <div class="sidebar-info-item" title="${escapeAttr(s.description)}" onclick="switchToSkill('${escapeAttr(s.name)}')" style="cursor:pointer">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;color:var(--primary)">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
            </svg>
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(s.name)}</span>
        </div>
    `).join('');
}

function switchToSkill(name) {
    const input = document.getElementById('chat-input');
    input.value = `@${name} `;
    input.focus();
}

async function loadSkills() {
    try {
        const res = await fetch(`${API_BASE}/api/skills`);
        state.skills = await res.json();
        renderSkillsGrid();
        renderSkillsDropdown();
        renderSkillsSidebar();
    } catch (e) {
        console.error('Failed to load skills:', e);
    }
}

// ============ Send Message ============
function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text || state.isStreaming) return;

    state.isStreaming = true;
    document.getElementById('send-btn').disabled = true;

    input.value = '';
    input.style.height = 'auto';

    // Show user message first, then assistant bubble
    appendUserMessage(text);

    // Show typing indicator (create bubble so processing element exists)
    state.currentAssistant = { content: '', tools: [] };
    appendAssistantBubble();

    // Now show processing text inside the bubble
    showProcessing('正在调用大模型...');

    // Update chat title with first message
    const chatTitle = document.getElementById('chat-title');
    if (chatTitle && chatTitle.textContent === '新对话') {
        chatTitle.textContent = text.substring(0, 10).replace(/\n/g, ' ').trim() + (text.length > 10 ? '...' : '');
    }

    if (state.wsConnected) {
        sendWS({ message: text });
    } else {
        // WS not connected — try HTTP fallback and remind user
        appendSystemMessage('WebSocket 未连接，使用 HTTP 模式发送...');
        sendViaHTTP(text);
    }
}

async function sendViaHTTP(text) {
    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text }),
        });
        const data = await res.json();
        if (data.error) {
            appendSystemMessage('Error: ' + data.error);
        } else {
            state.currentAssistant = { content: data.response || '', tools: [] };
            appendAssistantBubble();
            updateAssistantBubble(data.response);
            finalizeAssistantMessage();
        }
    } catch (e) {
        appendSystemMessage('Network error: ' + e.message);
    } finally {
        hideProcessing();
        state.isStreaming = false;
        document.getElementById('send-btn').disabled = !document.getElementById('chat-input').value.trim();
    }
}

function clearChat() {
    fetch(`${API_BASE}/api/clear`, { method: 'POST' });
    clearChatUI();
}

async function newSession() {
    try {
        const res = await fetch(`${API_BASE}/api/new-session`, { method: 'POST' });
        const data = await res.json();
        if (data.session_id) {
            state.currentSessionId = data.session_id;
        }
    } catch (e) {
        console.error('Failed to create new session:', e);
    }

    // Switch to chat view and clear UI
    switchView('chat');
    clearChatUI();
    document.getElementById('chat-title').textContent = '新对话';

    // Refresh history to show the old session
    loadHistory();
}

// ============ Message Rendering ============
function clearChatUI() {
    hideProcessing();
    state.isStreaming = false;
    state.currentAssistant = null;
    const container = document.getElementById('chat-messages');
    container.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon">M</div>
            <h1>你好，我是 MiniAgent</h1>
            <p>轻量级 AI Agent，支持 Skills + Tools，帮你完成各种任务</p>
            <div class="welcome-features">
                <div class="feature-card" data-action="file">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    <span>文件操作</span>
                </div>
                <div class="feature-card" data-action="code">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                    <span>代码执行</span>
                </div>
                <div class="feature-card" data-action="ai">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                    <span>AI 对话</span>
                </div>
                <div class="feature-card" data-action="skills">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
                    <span>Skills</span>
                </div>
            </div>
        </div>
    `;
    // Re-bind feature cards
    container.querySelectorAll('.feature-card').forEach(card => {
        card.addEventListener('click', () => {
            const action = card.dataset.action;
            if (action === 'skills') switchView('skills');
            else switchView('chat');
        });
    });
}

function appendUserMessage(text) {
    removeWelcome();
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message user';
    div.innerHTML = `
        <div class="message-avatar">U</div>
        <div class="message-content">${escapeHtml(text)}</div>
    `;
    container.appendChild(div);
    scrollToBottom(true);
}

function appendAssistantBubble() {
    removeWelcome();
    // Reset streaming render state for new message
    _lastRenderedLen = 0;
    _renderScheduled = false;
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.id = 'current-assistant-msg';
    div.innerHTML = `
        <div class="message-avatar">M</div>
        <div class="message-content">
            <div id="current-tool-cards"></div>
            <div id="current-assistant-text">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
            <div id="processing-indicator" class="processing-indicator" style="display:none"></div>
        </div>
    `;
    container.appendChild(div);
    scrollToBottom(true);
}

function isUserNearBottom() {
    const container = document.getElementById('chat-messages');
    if (!container) return true;
    return container.scrollHeight - container.scrollTop - container.clientHeight <= 150;
}

// ---- Streaming render throttle ----
// raw content length changed since last render
let _lastRenderedLen = 0;
// rAF throttle flag
let _renderScheduled = false;

/**
 * Schedule a DOM render via requestAnimationFrame.
 *
 * Streaming text chunks can arrive at >100 Hz (e.g. every 5–10 ms).
 * Calling formatMessageContent + innerHTML on every chunk causes
 * quadratic DOM work for long messages.
 *
 * rAF throttling batches all chunks within one ~16ms frame into a
 * single render, while still keeping the output visually smooth.
 */
function _scheduleBubbleRender(el) {
    if (_renderScheduled) return;
    _renderScheduled = true;
    requestAnimationFrame(() => {
        _renderScheduled = false;
        const content = state.currentAssistant?.content || '';
        // Skip if nothing rendered yet (typing indicator still showing)
        if (!content) return;
        // Skip if no new content since last render — avoid wasted work
        // when multiple tool messages arrive but no text was added
        if (content.length <= _lastRenderedLen) return;

        const nearBottom = isUserNearBottom();
        el.innerHTML = formatMessageContent(content);
        _lastRenderedLen = content.length;
        if (nearBottom) scrollToBottom(true);
    });
}

function updateAssistantBubble(content) {
    const el = document.getElementById('current-assistant-text');
    if (el) {
        _scheduleBubbleRender(el);
    }
    // Reset render tracker when a new message starts (content shorter = new message)
    if (content.length < _lastRenderedLen) {
        _lastRenderedLen = 0;
    }
}

function appendToolCard(name, args, idx) {
    const container = document.getElementById('current-tool-cards');
    if (!container) return;
    // Dedup: skip if card already exists
    if (document.getElementById(`tool-card-${idx}`)) return;
    const argsStr = (args && typeof args === 'object')
        ? JSON.stringify(args, null, 2)
        : (typeof args === 'string' ? args : String(args || ''));
    const card = document.createElement('div');
    card.className = 'tool-card expanded';  // expanded by default
    card.id = `tool-card-${idx}`;
    card.innerHTML = `
        <div class="tool-card-header" onclick="toggleToolCard(${idx})">
            <span class="tool-icon">&#9881;</span>
            <span class="tool-name">${escapeHtml(name)}</span>
            <span class="tool-status running" id="tool-status-${idx}">生成参数中...</span>
        </div>
        <div class="tool-card-body">
            <div class="tool-args" id="tool-args-${idx}">${escapeHtml(argsStr)}</div>
        </div>
    `;
    // Check BEFORE appending — only scroll if user hasn't scrolled up
    const nearBottom = isUserNearBottom();
    container.appendChild(card);
    if (nearBottom) scrollToBottom(true);
}

// Stream args text into an existing tool card in real-time
function appendToolCardArgs(idx, chunk) {
    const argsEl = document.getElementById(`tool-args-${idx}`);
    if (!argsEl) {
        console.warn(`[tool_args] element #tool-args-${idx} not found`);
        return;
    }
    const current = argsEl.textContent || '';
    // Limit to 5000 chars to avoid DOM bloat with huge HTML
    if (current.length > 5000) return;
    // Check BEFORE DOM mutation
    const nearBottom = isUserNearBottom();
    argsEl.textContent = current + chunk;
    // Also track in state for later use (e.g., file preview)
    if (state.currentAssistant && state.currentAssistant.tools[idx]) {
        state.currentAssistant.tools[idx].args = (state.currentAssistant.tools[idx].args || '') + chunk;
    }
    if (nearBottom) scrollToBottom(true);
}

function updateToolCard(toolInfo, idx) {
    const card = document.getElementById(`tool-card-${idx}`);
    if (!card) return;
    const status = document.getElementById(`tool-status-${idx}`);
    if (status) {
        status.textContent = '已完成';
        status.className = 'tool-status done';
    }
    // Hide streamed args area — only show result when done
    const argsEl = card.querySelector(`#tool-args-${idx}`);
    if (argsEl) argsEl.style.display = 'none';
    if (toolInfo.result) {
        const body = card.querySelector('.tool-card-body');
        if (body) {
            let html = `<div class="tool-result-label">Result:</div>`;
            html += `<div class="tool-result">${escapeHtml(toolInfo.result)}</div>`;
            if (toolInfo.truncated) {
                html += `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">(Output truncated)</div>`;
            }
            body.innerHTML += html;
        }
    }
}

function finalizeAssistantMessage() {
    if (state.currentAssistant) {
        // Clean up transitional status phrases from LLM output (e.g. "正在生成文件...")
        const textEl = document.getElementById('current-assistant-text');
        if (state.currentAssistant.content) {
            state.currentAssistant.content = state.currentAssistant.content
                .replace(/\*{0,2}正在(生成|执行|处理|保存|写入|创建|准备)[^\n]*\.{3,}\*{0,2}\s*\n?/g, '')
                .replace(/^\s+|\s+$/g, '');
        }

        // If no text content was generated but tools were executed, show a summary
        if (textEl && !state.currentAssistant.content && state.currentAssistant.tools.length > 0) {
            const doneCount = state.currentAssistant.tools.filter(t => t.done).length;
            const toolNames = state.currentAssistant.tools.map(t => t.name).join(', ');
            const summary = `✓ 通过 ${toolNames} 完成了 ${doneCount} 个工具调用`;
            state.currentAssistant.content = summary;
            textEl.innerHTML = `<p>${escapeHtml(summary)}</p>`;
        }

        const el = document.getElementById('current-assistant-msg');
        if (el) el.removeAttribute('id');
        if (textEl) textEl.removeAttribute('id');
        const tools = document.getElementById('current-tool-cards');
        if (tools) tools.removeAttribute('id');
        hideProcessing();
    }
    state.currentAssistant = null;
    state.isStreaming = false;
    hideProcessing();
    document.getElementById('send-btn').disabled = !document.getElementById('chat-input').value.trim();
    // If user scrolled up during response, don't yank them back to bottom
    if (isUserNearBottom()) scrollToBottom(true);
}

function appendSystemMessage(text) {
    removeWelcome();
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message system';
    div.innerHTML = `
        <div class="message-avatar">&#9432;</div>
        <div class="message-content">${formatMessageContent(text)}</div>
    `;
    container.appendChild(div);
    scrollToBottom(true);
}

// ============ Markdown Rendering Pipeline ============

/**
 * Extract fenced ```code blocks``` from content.
 * Returns cleaned content with placeholders, and the extracted blocks.
 */
function _extractFencedBlocks(content) {
    const blocks = [];
    const clean = content.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        blocks.push({ lang, code });
        return `%%CB_${blocks.length - 1}%%`;
    });
    return { clean, blocks };
}

/**
 * Strip raw HTML tags that the LLM might accidentally generate.
 */
function _stripLlmHtml(content) {
    let c = content;
    c = c.replace(/<br\s*\/?>/gi, '\n');
    c = c.replace(/<\/p>/gi, '\n').replace(/<p[^>]*>/gi, '');
    c = c.replace(/<\/div>/gi, '\n').replace(/<div[^>]*>/gi, '');
    c = c.replace(/<a\b[^>]*>(.*?)<\/a>/gi, '$1');
    return c;
}

/**
 * Convert fenced ``` code blocks to styled HTML with copy buttons.
 */
function _renderCodeBlocksToHtml(html) {
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const id = 'cb-' + Math.random().toString(36).substr(2, 6);
        codeBlocks.push(
            `<div style="position:relative"><pre><code id="${id}">${code.trim()}</code></pre><button class="code-copy-btn" onclick="copyCode('${id}')">Copy</button></div>`
        );
        return `%%CODEBLOCK_${codeBlocks.length - 1}%%`;
    });
    return { html, codeBlocks };
}

/**
 * Apply inline markdown: `code`, **bold**, [links](url).
 */
function _renderInlineMarkdown(html) {
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    return html;
}

/**
 * Convert absolute file paths to clickable <span> links.
 * Only converts the first occurrence of each normalized path.
 */
function _renderFileLinks(html) {
    const linkedPaths = new Set();

    function _norm(p) {
        return p.replace(/\\/g, '/').replace(/\/{2,}/g, '/');
    }
    function _buildLink(path) {
        const escaped = path.replace(/"/g, '&quot;');
        return `<span class="file-link" data-path="${escaped}" onclick="copyFilePath(this)" title="点击复制路径">${path}</span>`;
    }

    // <code>-wrapped absolute paths → link (first occurrence only)
    html = html.replace(/<code>([^<]+)<\/code>/g, (_, codeContent) => {
        const isAbsPath = /^[A-Za-z]:[/\\][^\s<>"{}()*|]+\.\w{1,10}$/.test(codeContent);
        if (isAbsPath) {
            if (linkedPaths.has(_norm(codeContent))) return `<code>${codeContent}</code>`;
            linkedPaths.add(_norm(codeContent));
            return _buildLink(codeContent);
        }
        return `<code>${codeContent}</code>`;
    });

    // Bare absolute paths → link (first occurrence only)
    const fileExtRe = /([A-Za-z]:[/\\](?:[^\s<>"{}\[\]()*|:;,]+[/\\])*[^\s<>"{}\[\]()*|:;,]+\.[a-zA-Z0-9]{1,10})(?=[\s。，,;；：）\)\]\}>'"\u201d\u2019<]|$)/g;
    html = html.replace(fileExtRe, (match) => {
        if (linkedPaths.has(_norm(match))) return match;
        linkedPaths.add(_norm(match));
        return _buildLink(match);
    });

    return html;
}

/**
 * Wrap all <a> tags in placeholders so subsequent processing won't break them.
 */
function _protectAnchors(html) {
    const placeholders = [];
    html = html.replace(/<a\b[^>]*>.*?<\/a>/gi, (match) => {
        const idx = placeholders.length;
        placeholders.push(match);
        return `%%ANCHOR_${idx}%%`;
    });
    return { html, placeholders };
}

/**
 * Restore code block and anchor placeholders.
 */
function _restorePlaceholders(html, codeBlocks, anchors) {
    html = html.replace(/%%ANCHOR_(\d+)%%/g, (_, i) => anchors[parseInt(i)]);
    html = html.replace(/%%CODEBLOCK_(\d+)%%/g, (_, i) => codeBlocks[parseInt(i)]);
    return html;
}

/**
 * Extract markdown tables, replace with placeholders, return {html, tables}.
 * Tables are multi-line: header row, separator row, one or more data rows.
 */
function _extractMarkdownTables(html) {
    const tables = [];
    // Match table blocks: consecutive lines of | ... | format
    // Each line: starts with |, contains groups of non-pipe chars ending in |, optional trailing space
    const tableRe = /(?:^\|(?:[^|\n]+\|)+\s*$\n?)+/gm;
    html = html.replace(tableRe, (match) => {
        const lines = match.trim().split(/\n/);
        if (lines.length < 3) return match; // Need header + separator + ≥1 data row
        // Verify second line is a separator (|---...|)
        if (!/^\|[\s:-]+\|/.test(lines[1])) return match;
        // Render table
        let tableHtml = '<table><thead><tr>';
        const headers = lines[0].split('|').filter(c => c.trim() !== '');
        headers.forEach(h => { tableHtml += '<th>' + h.trim() + '</th>'; });
        tableHtml += '</tr></thead><tbody>';
        for (let i = 2; i < lines.length; i++) {
            const cells = lines[i].split('|').filter(c => c.trim() !== '');
            tableHtml += '<tr>';
            cells.forEach(c => { tableHtml += '<td>' + c.trim() + '</td>'; });
            tableHtml += '</tr>';
        }
        tableHtml += '</tbody></table>';
        const idx = tables.length;
        tables.push(tableHtml);
        return '%%TBL_' + idx + '%%';
    });
    return { html, tables };
}

/**
 * Convert newlines to paragraphs and line breaks.
 * Protected content (placeholders) must already be extracted.
 */
function _assembleParagraphs(html) {
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p>\s*<\/p>/g, '');
    return html;
}

/**
 * Convert LLM response text to rendered HTML.
 *
 * Pipeline:  extract code blocks → strip raw HTML → escape → restore blocks
 *          → render code → inline markdown → file links → protect anchors
 *          → restore placeholders → paragraphs.
 */
function formatMessageContent(content) {
    if (!content) return '';

    // Step 0–1: Extract fenced code blocks, strip LLM-generated raw HTML
    const { clean: preCleaned, blocks: cbBlocks } = _extractFencedBlocks(content);
    let clean = _stripLlmHtml(preCleaned);

    // Step 2: HTML-escape then restore fenced blocks (their content is escaped later)
    let html = escapeHtml(clean);
    html = html.replace(/%%CB_(\d+)%%/g, (_, i) => {
        const b = cbBlocks[parseInt(i)];
        return '```' + b.lang + '\n' + escapeHtml(b.code) + '```';
    });

    // Step 3: Render code blocks to styled HTML with copy buttons
    const rendered = _renderCodeBlocksToHtml(html);
    const codeBlocks = rendered.codeBlocks;
    html = rendered.html;

    // Step 3.5: Extract markdown tables into placeholders (protect from paragraph breaking)
    const tableData = _extractMarkdownTables(html);
    html = tableData.html;
    const tables = tableData.tables;

    // Step 4: Inline markdown — `code`, **bold**, [links](url)
    html = _renderInlineMarkdown(html);

    // Step 5: Convert absolute file paths to clickable links
    html = _renderFileLinks(html);

    // Step 6: Protect <a> tags from being broken by subsequent processing
    const result = _protectAnchors(html);
    html = _restorePlaceholders(result.html, codeBlocks, result.placeholders);

    // Step 7: Paragraphs and line breaks
    html = _assembleParagraphs(html);

    // Step 7.5: Unwrap table placeholders from <p> tags (browsers auto-close <p> before <table>)
    html = html.replace(/<p>\s*%%TBL_(\d+)%%\s*<\/p>/g, '%%TBL_$1%%');

    // Step 8: Restore table HTML
    html = html.replace(/%%TBL_(\d+)%%/g, (_, i) => tables[parseInt(i)] || '');

    return html;
}

// ============ Skills Rendering ============
function renderSkillsGrid() {
    const grid = document.getElementById('skills-grid');
    if (state.skills.length === 0) {
        grid.innerHTML = '<div class="loading">暂无可用的 Skills</div>';
        return;
    }

    grid.innerHTML = state.skills.map(skill => {
        const iconInfo = getSkillIconInfo(skill.name, skill.description || '');
        const desc = (skill.description || '').replace(/\n/g, ' ').substring(0, 100);
        const triggers = skill.triggers || [];
        return `
            <div class="skill-card" data-name="${escapeAttr(skill.name)}">
                <div class="skill-card-header">
                    <div class="skill-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                        </svg>
                    </div>
                    <span class="skill-name">${escapeHtml(skill.name)}</span>
                    ${skill.always ? '<span class="skill-type">always</span>' : ''}
                </div>
                <div class="skill-description">${escapeHtml(desc)}</div>
                <div class="skill-status">
                    <span class="status-dot available"></span>
                    <span>可用</span>
                </div>
                ${triggers.length > 0 ? `
                    <div class="skill-triggers">
                        ${triggers.slice(0, 6).map(t => `<span class="skill-trigger-tag">${escapeHtml(t)}</span>`).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');

    // Click to use skill
    grid.querySelectorAll('.skill-card').forEach(card => {
        card.addEventListener('click', () => {
            const name = card.dataset.name;
            switchView('chat');
            const input = document.getElementById('chat-input');
            input.value = `@${name} `;
            input.focus();
        });
    });
}

function renderSkillsDropdown() {
    const dropdown = document.getElementById('skills-dropdown');
    if (!dropdown) return;

    if (state.skills.length === 0) {
        dropdown.innerHTML = '<div class="dropdown-empty">暂无可用 Skills</div>';
        return;
    }

    let html = '<div class="dropdown-search"><input type="text" placeholder="搜索技能..." id="skills-search-input"></div>';
    html += '<div class="dropdown-list">';
    state.skills.forEach(skill => {
        const iconInfo = getSkillIconInfo(skill.name, skill.description || '');
        const desc = (skill.description || '').replace(/\n/g, ' ').substring(0, 80);
        html += `
            <div class="dropdown-item" data-name="${escapeAttr(skill.name)}" data-desc="${escapeAttr(desc)}">
                <span class="dropdown-item-icon ${iconInfo.cls}">${iconInfo.icon}</span>
                <div class="dropdown-item-info">
                    <span class="dropdown-item-name">${escapeHtml(skill.name)}</span>
                    <span class="dropdown-item-desc">${escapeHtml(desc)}</span>
                </div>
                ${skill.always ? '<span class="dropdown-item-badge">always</span>' : ''}
            </div>
        `;
    });
    html += '</div>';
    dropdown.innerHTML = html;

    // Search filter
    const searchInput = dropdown.querySelector('#skills-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            dropdown.querySelectorAll('.dropdown-item').forEach(item => {
                const name = item.dataset.name.toLowerCase();
                const desc = (item.dataset.desc || '').toLowerCase();
                item.style.display = (name.includes(query) || desc.includes(query)) ? '' : 'none';
            });
        });
    }

    // Click to select
    dropdown.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', () => {
            insertSkillReference(item.dataset.name);
            closeSkillsDropdown();
        });
    });
}

function getSkillIconInfo(name, description) {
    const text = (name + ' ' + description).toLowerCase();
    if (text.includes('ppt') || text.includes('pptx'))
        return { icon: 'P', cls: 'skill-icon-tool' };
    if (text.includes('重写') || text.includes('book') || text.includes('书籍'))
        return { icon: 'B', cls: 'skill-icon-ai' };
    if (text.includes('prd') || text.includes('需求'))
        return { icon: 'D', cls: 'skill-icon-tool' };
    if (text.includes('hello') || text.includes('你好'))
        return { icon: 'H', cls: 'skill-icon-default' };
    if (text.includes('shell'))
        return { icon: 'S', cls: 'skill-icon-shell' };
    return { icon: name.charAt(0).toUpperCase(), cls: 'skill-icon-default' };
}

function insertSkillReference(skillName) {
    const input = document.getElementById('chat-input');
    if (!input) return;
    const val = input.value;
    if (val.length > 0 && !val.endsWith('\n') && !val.endsWith(' ')) {
        input.value = val + ' ';
    }
    input.value += `@${skillName} `;
    input.focus();
}

function toggleSkillsDropdown() {
    const dropdown = document.getElementById('skills-dropdown');
    if (!dropdown) return;
    state.skillsDropdownVisible = !state.skillsDropdownVisible;
    dropdown.classList.toggle('visible', state.skillsDropdownVisible);
    if (state.skillsDropdownVisible && state.skills.length === 0) {
        loadSkills();
    }
}

function closeSkillsDropdown() {
    const dropdown = document.getElementById('skills-dropdown');
    if (dropdown) {
        state.skillsDropdownVisible = false;
        dropdown.classList.remove('visible');
    }
}

// ============ Utilities ============
function removeWelcome() {
    const welcome = document.querySelector('.welcome-message');
    if (welcome) welcome.remove();
}

function scrollToBottom(force = false) {
    requestAnimationFrame(() => {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        // If the user has scrolled up (more than 150px from bottom), don't auto-scroll
        // unless force=true (e.g., after appending a new user message or loading history)
        if (!force) {
            const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
            if (distanceFromBottom > 150) return;
        }
        container.scrollTop = container.scrollHeight;
    });
}

function toggleToolCard(idx) {
    const card = document.getElementById(`tool-card-${idx}`);
    if (card) card.classList.toggle('expanded');
}

function copyCode(id) {
    const el = document.getElementById(id);
    if (el) {
        navigator.clipboard.writeText(el.textContent).then(() => {
            const btn = el.closest('div').querySelector('.code-copy-btn');
            if (btn) {
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy', 1500);
            }
        });
    }
}

function copyFilePath(el) {
    const path = el.getAttribute('data-path') || el.textContent;
    navigator.clipboard.writeText(path).then(() => {
        el.classList.add('copied');
        showToast('路径已复制: ' + path);
        setTimeout(() => el.classList.remove('copied'), 1500);
    }).catch(() => {
        showToast('复制失败，请手动复制');
    });
}

function showToast(msg) {
    // Remove existing toast
    const old = document.querySelector('.miniagent-toast');
    if (old) old.remove();
    const toast = document.createElement('div');
    toast.className = 'miniagent-toast';
    toast.textContent = msg;
    document.body.appendChild(toast);
    // Trigger animation
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}



// Processing state: show a small status line below the assistant message
function showProcessing(text) {
    const container = document.getElementById('processing-indicator');
    if (container) {
        container.textContent = text;
        container.style.display = 'block';
    }
}

function hideProcessing() {
    const container = document.getElementById('processing-indicator');
    if (container) {
        container.style.display = 'none';
        container.textContent = '';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ============ History Management ============

async function loadHistory() {
    const container = document.getElementById('history-sidebar');
    if (!container) return;

    container.innerHTML = '<div class="history-loading">加载中...</div>';

    try {
        const response = await fetch(`${API_BASE}/api/recent-sessions?limit=20`);
        const data = await response.json();

        if (data.error) {
            container.innerHTML = `<div class="history-empty">加载失败</div>`;
            updateHistoryCount(0);
            return;
        }

        if (!data.sessions || data.sessions.length === 0) {
            container.innerHTML = '<div class="history-empty">暂无历史记录</div>';
            updateHistoryCount(0);
            return;
        }

        updateHistoryCount(data.sessions.length);

        container.innerHTML = data.sessions.map(session => {
            // Title: prefer DB title, fallback to first 10 chars of first message
            const title = session.title
                || (session.first_message ? session.first_message.substring(0, 10) : '未命名对话');

            const isActive = session.session_id === state.currentSessionId;

            return `
                <div class="history-item ${isActive ? 'active' : ''}"
                     data-session-id="${escapeAttr(session.session_id)}"
                     title="${escapeAttr(session.first_message || title)}">
                    <div class="history-item-user">${escapeHtml(title)}</div>
                    <div class="history-item-preview">${escapeHtml(truncateText(session.first_message || '', 40))}</div>
                    <div class="history-item-time">${formatTime(session.updated_at)} · ${session.message_count || 0}条</div>
                    <button class="history-delete-btn" title="删除此对话" data-sid="${escapeAttr(session.session_id)}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                    </button>
                </div>
            `;
        }).join('');

        // Click to load session
        container.querySelectorAll('.history-item').forEach(item => {
            item.addEventListener('click', (e) => {
                // Don't trigger when clicking delete button
                if (e.target.closest('.history-delete-btn')) return;
                loadSession(item.dataset.sessionId);
            });
        });

        // Delete button handlers
        container.querySelectorAll('.history-delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const sid = btn.dataset.sid;
                if (confirm('确定要删除这个历史对话吗？')) {
                    deleteSession(sid);
                }
            });
        });

    } catch (error) {
        console.error('Failed to load history:', error);
        container.innerHTML = '<div class="history-empty">加载失败</div>';
        updateHistoryCount(0);
    }
}

function updateHistoryCount(count) {
    const el = document.getElementById('history-count');
    if (el) el.textContent = `(${count})`;
}

async function deleteSession(sessionId) {
    try {
        const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'ok') {
            // If the deleted session was the current one, clear UI
            if (state.currentSessionId === sessionId) {
                state.currentSessionId = null;
                clearChatUI();
                document.getElementById('chat-title').textContent = '新对话';
            }
            // Refresh the history list
            loadHistory();
        } else {
            console.error('Delete failed:', data.error);
        }
    } catch (e) {
        console.error('Failed to delete session:', e);
    }
}

async function loadSession(sessionId) {
    try {
        // Switch engine to this session
        const switchRes = await fetch(`${API_BASE}/api/sessions/${sessionId}/switch`, { method: 'POST' });
        const switchData = await switchRes.json();
        if (switchData.session_id) {
            state.currentSessionId = switchData.session_id;
        }

        // Load messages
        const msgRes = await fetch(`${API_BASE}/api/sessions/${sessionId}/messages?limit=100`);
        const msgData = await msgRes.json();

        if (msgData.error) {
            appendSystemMessage('加载对话失败: ' + msgData.error);
            return;
        }

        // Clear and rebuild UI
        clearChatUI();

        const messages = msgData.messages || [];
        if (messages.length === 0) {
            return;
        }

        // Render all messages
        for (const msg of messages) {
            if (msg.role === 'user') {
                appendUserMessage(msg.content);
            } else if (msg.role === 'assistant') {
                // For historical messages, just show as static text
                removeWelcome();
                const container = document.getElementById('chat-messages');
                const div = document.createElement('div');
                div.className = 'message assistant';
                div.innerHTML = `
                    <div class="message-avatar">M</div>
                    <div class="message-content">${formatMessageContent(msg.content)}</div>
                `;
                container.appendChild(div);
            }
        }

        scrollToBottom(true);

        // Update chat title
        const title = messages.find(m => m.role === 'user');
        if (title) {
            document.getElementById('chat-title').textContent =
                title.content.substring(0, 10).replace(/\n/g, ' ').trim() + '...';
        }

        // Switch to chat view
        switchView('chat');

        // Refresh history to update active state
        loadHistory();

    } catch (error) {
        console.error('Failed to load session:', error);
        appendSystemMessage('加载对话失败');
    }
}

function truncateText(text, maxLength) {
    if (!text) return '';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    try {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;

        // Less than 1 hour
        if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return minutes < 1 ? '刚刚' : `${minutes}分钟前`;
        }

        // Less than 24 hours
        if (diff < 86400000) {
            const hours = Math.floor(diff / 3600000);
            return `${hours}小时前`;
        }

        // More than 24 hours
        const days = Math.floor(diff / 86400000);
        if (days < 7) {
            return `${days}天前`;
        }

        // Show date
        return date.toLocaleDateString('zh-CN');
    } catch (e) {
        return '';
    }
}

function initHistoryRefresh() {
    const refreshBtn = document.getElementById('refresh-history');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadHistory();
        });
    }

    // Collapse/expand toggle
    const toggleBtn = document.getElementById('toggle-history');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            const historyList = document.getElementById('history-sidebar');
            if (historyList) {
                historyList.classList.toggle('collapsed');
                toggleBtn.classList.toggle('collapsed');
            }
        });
    }

    // Auto-load history on page load
    setTimeout(() => {
        loadHistory();
    }, 1000);
}

