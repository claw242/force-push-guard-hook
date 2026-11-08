# force-push-guard-hook

Loupe & Lettres — créé avec l'aide de l'IA (created with the help of AI). This repository is published by an AI-assisted shop, not by a named person.

A single-file Python `PreToolUse` hook that refuses `git push --force`, `-f`, `+refspec` pushes, `--mirror` and deletion of protected remote branches when an AI coding agent proposes them. Plain pushes and tags pass.

## Install (Claude Code, `.claude/settings.json`)

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash",
  "hooks": [{"type": "command", "command": "python3 /path/to/block_force_push.py"}]}]}}
```

## Try it without running any git command

The hook reads the tool call as JSON on stdin; nothing is executed.

```
echo '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}' | python3 block_force_push.py ; echo $?
```

Exit code 2 = blocked (reason on stderr). Exit 0 = not refused by these rules. Run the included tests with `python3 -m unittest discover -p "test_*.py"`.

## Limits (read before relying on it)

It is a seat belt, not a sandbox: a git alias, a script or a variable that builds the command at run time can hide a force push. The text of a heredoc is read as commands, so a harmless note can be refused. Review the code before use. Provided as is; not affiliated with Anthropic or any agent vendor. It was written with AI assistance and checked with the fixture tests above; it has not been audited by a third party.

Leading shell redirections (including descriptor prefixes) and abbreviated dangerous
push flags are refused conservatively. This can also refuse a harmless redirected
command. Redirection tokens anywhere in a recognized Git command are also refused.
Fixture tests do not establish an installed Claude Code session; that
integration is unverified. Keep the host's ordinary permission checks enabled.

## More

This hook is one of three in the paid **Agent Hook Starter** (also covers destructive commands and secret paths): https://loupeetlettres.gumroad.com/l/agent-hook-starter — shop: https://loupeetlettres.gumroad.com/
