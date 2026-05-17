# MiniAgent

精简版 AI Agent：Chat + Skills，接入千问模型。

## 快速开始

```bash
pip install openai pyyaml
python main.py
```

## 配置

编辑 `config.json`：

```json
{
  "model": "qwen-plus",
  "api_key": "sk-xxxxx",
  "temperature": 0.7,
  "max_tokens": 4096
}
```

- `api_key` 也支持环境变量 `DASHSCOPE_API_KEY`
- 默认 API 端点：`https://dashscope.aliyuncs.com/compatible-mode/v1`

## Skills

将 Skill 放在 `~/.miniagent/skills/<skill-name>/SKILL.md`。

Skill 支持可选的 YAML frontmatter：

```markdown
---
description: "Skill 描述"
triggers:
  - "关键词1"
  - "关键词2"
---

# Skill 内容

这里是 skill 的具体指令...
```

- `description`：skill 简述，显示在列表中
- `triggers`：触发关键词列表，用户输入包含这些词时自动加载
- 没有 triggers 的 skill 不会自动加载，只能手动指定
