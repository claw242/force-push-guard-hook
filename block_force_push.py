#!/usr/bin/env python3
"""PreToolUse hook: stop an AI coding agent from force-pushing or deleting remote branches.

Made by Loupe & Lettres, créé avec l'aide de l'IA (created with the help of AI). Fourni tel quel, à relire
avant usage (provided as is, review before use). Non affilié à Anthropic ni à aucun fournisseur d'agent
(not affiliated with Anthropic or any agent vendor).

Known limits: the text of a heredoc is read as if it were commands (a harmless note can be refused);
variables, aliases and scripts that build a command at run time are not followed.
Leading redirections and abbreviated dangerous push options are refused conservatively.

Install (Claude Code, .claude/settings.json):
  {"hooks": {"PreToolUse": [{"matcher": "Bash",
    "hooks": [{"type": "command", "command": "python3 /path/to/block_force_push.py"}]}]}}

Blocked: git push --force / -f / +refspec / --mirror, --force-with-lease unless it names a non-protected
branch, and deleting a protected branch on the remote. Everything else (plain pushes, tags) passes.
Exit 2 blocks (reason on stderr, shown to the agent); malformed input is refused (fail closed).
It is a seat belt, not a sandbox: a git alias or a script can hide a force push. Review before use.
"""
import json
import re
import sys

# --- local shell parser, adapted to conservatively refuse leading redirections ---
import json
import os
import re
import shlex

# Wrapper commands that only launch another command, mapped to the options that consume a value.
_WRAPPERS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S"},
    "command": set(),
    "builtin": set(),
    "exec": {"-a"},
    "nohup": set(),
    "time": {"-f", "-o"},
    "nice": {"-n"},
    "timeout": {"-s", "-k"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a"},
    "stdbuf": {"-i", "-o", "-e"},
}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
# Shell keywords that can sit in front of a real command (`if true; then rm ...`, `! rm ...`).
_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done", "esac"}
_MAX_DEPTH = 4
_MAX_INPUT_CHARS = 1_000_000
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def validate_payload(raw):
    """Validate the hook transport before any tool-specific rule uses its fields."""
    if len(raw) > _MAX_INPUT_CHARS:
        raise ValueError("hook input exceeds supported size")
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ValueError("input is not supported JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError("tool_name must be a nonempty string")
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input must be an object")
    for key in ("path", "file_path", "notebook_path", "glob", "pattern", "content", "new_string", "new_source"):
        if key in tool_input and not isinstance(tool_input[key], str):
            raise ValueError("tool text fields must be strings")
    if tool == "Bash" and not isinstance(tool_input.get("command"), str):
        raise ValueError("Bash call requires a command string")
    if tool == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list) or any(
                not isinstance(edit, dict) or not isinstance(edit.get("new_string"), str) for edit in edits):
            raise ValueError("MultiEdit requires a list of text edits")
    return payload


def _balanced(command, start):
    """Return (text, next_index) of a $( ... ) body that begins at `start`."""
    depth, i = 1, start
    while i < len(command):
        if command[i] == "(":
            depth += 1
        elif command[i] == ")":
            depth -= 1
            if depth == 0:
                return command[start:i], i + 1
        i += 1
    return command[start:], len(command)


def _split(command):
    """Split on unquoted ; & | ( ) newline and backtick.

    Returns (segments, nested): segments are (operator_before, text) pairs, nested are the bodies of
    $(...) and `...` found inside double quotes (they run even though they are quoted).
    """
    segments, nested, buf = [], [], []
    pending, quote, i = "", None, 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            buf.append(ch)
            quote = None if ch == "'" else quote
        elif ch == "\\":
            buf.append(command[i:i + 2])
            i += 2
            continue
        elif quote == '"':
            if command.startswith("$(", i):
                inner, i = _balanced(command, i + 2)
                nested.append(inner)
                continue
            if ch == "`":
                end = command.find("`", i + 1)
                end = len(command) if end < 0 else end
                nested.append(command[i + 1:end])
                i = end + 1
                continue
            buf.append(ch)
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in ";&|\n()`":
            text = "".join(buf).strip()
            if text:
                segments.append((pending, text))
                buf, pending = [], ""
            pending += ch
        else:
            buf.append(ch)
        i += 1
    text = "".join(buf).strip()
    if text:
        segments.append((pending, text))
    return segments, nested


def _words(text):
    """Tokenize redirections separately, even when attached to a command or path."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars="<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError as error:
        raise ValueError("cannot parse shell quoting") from error


def _strip(words):
    """Drop VAR=value prefixes and wrapper commands (sudo, env, nohup...). Return the real argv."""
    i, last = 0, None
    while i < len(words):
        word = words[i]
        if word.startswith(("<", ">")) or (
                word.isdigit() and i + 1 < len(words) and words[i + 1].startswith(("<", ">"))):
            raise ValueError("leading shell redirections are not supported")
        if word in _KEYWORDS or _ASSIGNMENT.match(word):
            i += 1
            continue
        base = os.path.basename(word)
        if base not in _WRAPPERS:
            break
        last, i = base, i + 1
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] in _WRAPPERS[base] else 1
        if base == "timeout" and i < len(words):
            i += 1
    rest = words[i:]
    if not rest:
        return ["env"] if last == "env" else []
    return [os.path.basename(rest[0])] + rest[1:]


def _payload(argv):
    """The command string hidden inside `sh -c '...'` or `eval ...`, if any."""
    if argv[0] == "eval":
        return " ".join(argv[1:])
    if argv[0] not in _SHELLS:
        return None
    for index, word in enumerate(argv[1:], start=1):
        if not word.startswith("-"):
            return None
        if not word.startswith("--") and "c" in word[1:]:
            return argv[index + 1] if index + 1 < len(argv) else None
    return None


def commands(command, depth=0):
    """Yield (operator_before, argv) for every simple command, including those inside
    $(...), backticks, `sh -c '...'` and `eval ...`. argv[0] is the bare command name."""
    if depth > _MAX_DEPTH:
        raise ValueError("shell nesting exceeds supported depth")
    segments, nested = _split(command)
    for text in nested:
        yield from commands(text, depth + 1)
    for operator, text in segments:
        argv = _strip(_words(text))
        if not argv:
            continue
        yield operator, argv
        payload = _payload(argv)
        if payload:
            yield from commands(payload, depth + 1)
# --- end shared shell parser ---

PROTECTED = re.compile(r"^(?:main|master|trunk|develop|development|dev|production|prod|stable|release.*)$")
_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
_LEASE = re.compile(r"^--force-(?:with-lease|if-includes)(?:=.*)?$")
_GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def _push_args(argv):
    """Arguments after `git [global options] push`, or None when this is not a push."""
    if any(word.startswith(("<", ">")) for word in argv[1:]):
        raise ValueError("redirections in Git commands are not supported")
    rest = list(argv[1:])
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in _GIT_VALUE_OPTIONS else rest[1:]
    return rest[1:] if rest[:1] == ["push"] else None


def _split_args(args):
    """Return (flags, positionals, has_repo); without --repo the first positional is the remote."""
    flags, positionals, skip, has_repo = [], [], False, False
    for word in args:
        if skip:
            skip = False
        elif word in _VALUE_OPTIONS:
            skip = True
            has_repo = has_repo or word == "--repo"
        elif word.startswith("--repo="):
            has_repo = True
        elif word.startswith("-") and word != "-":
            flags.append(word)
        else:
            positionals.append(word)
    return flags, positionals, has_repo


def _branch(refspec):
    destination = refspec.lstrip("+").split(":")[-1]
    return destination[len("refs/heads/"):] if destination.startswith("refs/heads/") else destination


def check_push(argv):
    args = _push_args(argv)
    if args is None:
        return None
    flags, positionals, has_repo = _split_args(args)
    dangerous_long = ("--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete")
    for flag in flags:
        name = flag.split("=", 1)[0]
        if name.startswith("--") and name not in dangerous_long and any(
                option.startswith(name) for option in dangerous_long):
            return "abbreviated dangerous push option is not supported"
    refspecs = positionals if has_repo else positionals[1:]
    short = [f for f in flags if not f.startswith("--")]
    if "--force" in flags or any("f" in f[1:] for f in short):
        return "git push --force overwrites remote history"
    if "--mirror" in flags:
        return "git push --mirror overwrites every remote ref"
    if any(spec.startswith("+") for spec in refspecs):
        return "a +refspec forces the push"
    deleting = "--delete" in flags or any("d" in f[1:] for f in short)
    for spec in refspecs:
        target = _branch(spec)
        if (deleting or spec.startswith(":")) and PROTECTED.match(target):
            return "deleting the protected branch '%s' on the remote" % target
    if any(_LEASE.match(f) for f in flags):
        explicit = [_branch(s) for s in refspecs]
        if not explicit or any(PROTECTED.match(b) or b in {"HEAD", ""} for b in explicit):
            return "force-with-lease on a protected or unspecified branch"
    return None


def decide(payload):
    """Return a reason string to block the tool call, or None to allow."""
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return "tool_input must be an object"
    command = tool_input.get("command")
    if not isinstance(command, str):
        return "Bash call without a command string"
    for _, argv in commands(command):
        if argv[0] == "git":
            reason = check_push(argv)
            if reason:
                return reason
    return None


def parse_payload(raw):
    return validate_payload(raw)


def main():
    try:
        reason = decide(parse_payload(sys.stdin.read(_MAX_INPUT_CHARS + 1)))
    except ValueError as error:
        reason = "refused malformed hook input (%s)" % error
    if reason:
        sys.stderr.write("BLOCKED by block_force_push.py: %s. Ask the human to run it themselves if "
                         "it is really intended.\n" % reason)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
