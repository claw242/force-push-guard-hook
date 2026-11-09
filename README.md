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

## Worked example (what the hook prints)

Both commands send a fake tool call to the hook; nothing is executed. The first one is a force push, the second one a plain push.

```
$ echo '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}' | python3 block_force_push.py ; echo "exit $?"
BLOCKED by block_force_push.py: git push --force overwrites remote history. Ask the human to run it themselves if it is really intended.
exit 2

$ echo '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}' | python3 block_force_push.py ; echo "exit $?"
exit 0
```

Exit code 2 is what tells the agent host to refuse the tool call; any other exit code lets it through (that is why a hook that exits 1 by mistake protects nothing).

## Limits (read before relying on it)

It is a seat belt, not a sandbox: a git alias, a script or a variable that builds the command at run time can hide a force push. The text of a heredoc is read as commands, so a harmless note can be refused. Review the code before use. Provided as is; not affiliated with Anthropic or any agent vendor. It was written with AI assistance and checked with the fixture tests above; it has not been audited by a third party.

Leading shell redirections (including descriptor prefixes) and abbreviated dangerous
push flags are refused conservatively. This can also refuse a harmless redirected
command. Redirection tokens anywhere in a recognized Git command are also refused.
Fixture tests do not establish an installed Claude Code session; that
integration is unverified. Keep the host's ordinary permission checks enabled.

## More

This hook is one of three in the paid **Agent Hook Starter** (also covers destructive commands and secret paths): https://loupeetlettres.gumroad.com/l/agent-hook-starter — shop: https://loupeetlettres.gumroad.com/

Want to check a hook of your own against a corpus of safe and dangerous tool calls? **Hook Proof** (9 USD) is a hook tester: https://loupeetlettres.gumroad.com/l/gvdarr
Want more hook ideas beyond blocking (prompt checks, session context, post-edit checks, stop checks)? **Hook Cookbook** (8 USD): https://loupeetlettres.gumroad.com/l/dpehuq

Both are sold by Loupe & Lettres, an AI-assisted shop; this free repository works without them.
