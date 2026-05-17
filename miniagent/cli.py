"""CLI entry point for MiniAgent."""

import sys
import argparse
from pathlib import Path


def cmd_chat(args) -> None:
    """Interactive chat mode."""
    from .chat import ChatEngine
    from .config import load_config, get_config_path, get_app_dir

    # Load config
    project_config = Path(args.config) if args.config else None
    config = load_config(project_config)

    # Validate API key
    if not config.get("api_key"):
        print("Error: No API key configured.")
        print()
        print("Set your DashScope API key by one of:")
        print(f"  1. Edit {get_config_path()}")
        print("  2. Set environment variable: DASHSCOPE_API_KEY=sk-xxxxx")
        print()
        print("Get your API key from: https://dashscope.console.aliyun.com/")
        sys.exit(1)

    engine = ChatEngine(config)

    # One-shot query mode
    if args.query:
        response = engine.chat(args.query.strip())
        print(response)
        return

    # Print welcome
    print()
    print(f"  MiniAgent v1.1.0")
    print(f"  Model: {config.get('model', 'qwen-plus')}")
    print(f"  Skills dir: {config.get('skills_dir') or str(get_app_dir() / 'skills')}")

    # Tools
    tool_names = engine.tools.tool_names
    print(f"  Tools: {', '.join(tool_names)}")

    # Skills
    skills = engine.skills.list_all()
    if skills:
        print(f"  Skills loaded: {len(skills)}")
        for s in skills:
            tag = " (always)" if s.always else ""
            print(f"    - {s.name}: {s.description}{tag}")
    else:
        print("  No skills loaded. Add skills to ~/.miniagent/skills/")
    print()
    print("  Commands: /clear, /skills, /tools, /reload, /quit")
    print("  ─────────────────────────────────────")
    print()

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd in ("/quit", "/exit", "/q"):
                print("Goodbye!")
                break
            elif cmd == "/clear":
                engine.clear_history()
                print("  History cleared.")
                continue
            elif cmd == "/skills":
                skills = engine.skills.list_all()
                if not skills:
                    print("  No skills available.")
                else:
                    for s in skills:
                        tag = " [always]" if s.always else ""
                        triggers = f" (triggers: {', '.join(s.triggers)})" if s.triggers else ""
                        print(f"  - {s.name}{tag} — {s.description}{triggers}")
                continue
            elif cmd == "/tools":
                for name in engine.tools.tool_names:
                    tool = engine.tools.get(name)
                    print(f"  - {name}: {tool.description if tool else ''}")
                continue
            elif cmd == "/reload":
                engine.reload_skills()
                count = len(engine.skills.list_all())
                print(f"  Reloaded {count} skill(s).")
                continue
            elif cmd.startswith("/use "):
                # Manually activate a skill
                skill_name = user_input[5:].strip()
                skill = engine.skills.get(skill_name)
                if not skill:
                    print(f"  Skill '{skill_name}' not found.")
                else:
                    response = engine.chat("", active_skills=[skill], auto_match=False)
                    print(f"Assistant > {response}")
                continue
            else:
                print(f"  Unknown command: {user_input}")
                print("  Commands: /clear, /skills, /tools, /reload, /use <name>, /quit")
                continue

        # Normal chat
        response = engine.chat(user_input)
        print(f"Assistant > {response}")


def cmd_skills(args) -> None:
    """List or manage skills."""
    from .config import load_config, get_skills_dir
    from .skills import SkillsLoader

    config = load_config()
    skills_dir = get_skills_dir(config)
    loader = SkillsLoader(skills_dir)
    skills = loader.list_all()

    if args.init:
        skills_dir.mkdir(parents=True, exist_ok=True)
        # Create example skill
        example_dir = skills_dir / "hello"
        example_dir.mkdir(exist_ok=True)
        example_file = example_dir / "SKILL.md"
        if not example_file.exists():
            example_file.write_text(
                """---
description: "A greeting skill that responds with friendly hellos"
triggers:
  - "你好"
  - "hello"
  - "hi"
  - "嗨"
---

# Greeting Skill

When the user greets you, respond with a warm and friendly greeting.

Rules:
1. Always respond in the same language the user used
2. Include their greeting back (e.g., if they say "你好", include "你好" in your response)
3. Be enthusiastic but natural
4. Optionally ask how you can help today
""",
                encoding="utf-8",
            )
        print(f"  Skills directory created: {skills_dir}")
        print(f"  Example skill added: hello")
        print(f"  Add more skills to: {skills_dir}/<skill-name>/SKILL.md")
        return

    if not skills:
        print(f"  No skills found in {skills_dir}")
        print("  Run 'miniagent skills --init' to create example skills")
        return

    print(f"  Skills in {skills_dir}:")
    for s in skills:
        tag = " [always]" if s.always else ""
        triggers = f"\n    triggers: {', '.join(s.triggers)}" if s.triggers else ""
        print(f"  - {s.name}{tag} — {s.description}{triggers}")


def cmd_web(args) -> None:
    """Start web server with UI."""
    import uvicorn
    from .web import app
    from .config import load_config

    config = load_config()

    if not config.get("api_key"):
        print("Warning: No API key configured. Set it in ~/.miniagent/config.json")

    host = args.host or "0.0.0.0"
    port = args.port or 7860
    print()
    print(f"  MiniAgent Web Server")
    print(f"  URL: http://localhost:{port}")
    print(f"  Model: {config.get('model', 'qwen-plus')}")
    print(f"  Press Ctrl+C to stop")
    print()
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser(
        prog="miniagent",
        description="MiniAgent - Lightweight AI Agent with Chat + Skills",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # chat subcommand
    chat_parser = sub.add_parser("chat", help="Start interactive chat")
    chat_parser.add_argument(
        "-c", "--config",
        help="Path to project-level config.json",
        default=None,
    )
    chat_parser.add_argument(
        "-q", "--query",
        help="One-shot query mode: send a message and print the response, then exit",
        default=None,
    )

    # web subcommand
    web_parser = sub.add_parser("web", help="Start web server with UI")
    web_parser.add_argument(
        "--host",
        help="Host to bind (default: 0.0.0.0)",
        default=None,
    )
    web_parser.add_argument(
        "-p", "--port",
        help="Port to bind (default: 7860)",
        type=int,
        default=None,
    )

    # skills subcommand
    skills_parser = sub.add_parser("skills", help="Manage skills")
    skills_parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize skills directory with example skill",
    )

    args = parser.parse_args()

    if args.command == "web":
        cmd_web(args)
    elif args.command == "skills" or args.command is None:
        if hasattr(args, "init") and args.init:
            cmd_skills(args)
        elif args.command is None:
            # Default: start chat
            args.config = None
            args.query = None
            cmd_chat(args)
        else:
            cmd_skills(args)
    elif args.command == "chat":
        cmd_chat(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
