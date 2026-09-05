---
name: agent-cli-creator
description: Use when the user wants to build a CLI tool that automates a website through OpenBridge and the user's real Chrome session. Invoke for requests such as "create a CLI for X site", "build a tool to automate X", or programmatic browser control via an AI agent.
---

# Agent CLI Creator

Build a website-automation CLI backed by the [OpenBridge](https://github.com/60ke/openBridge) browser daemon and Chrome extension.

## Phase 1: Prerequisites

```bash
curl -s http://127.0.0.1:10088/health
```

Proceed only when `ok` is `true` and `connectedSessions` is non-empty. Also confirm that `browser_evaluate` is enabled in the extension popup; xx-cli implementations use it for DOM inspection and authenticated page-side `fetch` calls.

If `10088` is occupied, OpenBridge may choose `10089`–`10098`. Read `.openbridge-data/runtime.json` and export the active endpoint before generating or running a CLI:

```bash
export OPENBRIDGE_URL=http://127.0.0.1:<actual-port>
```

If OpenBridge is missing, install it with:

```bash
curl -fsSL https://raw.githubusercontent.com/60ke/openBridge/master/install.sh | bash
```

Then install/authorize the OpenBridge Chrome extension and run `openbridge start`.

## Phase 2: Requirements Interview

Ask the user in one message, then wait for the reply:

1. **Target website URL** (required)
2. **Programming language** — Go (recommended in this repo) / Python / Node.js / Other
3. **Login required?** — Yes / No / Unknown
4. **First 1–3 features** — read, write, or account-status operations

Explain that the first iteration intentionally validates only 1–3 features end-to-end; more commands can be added after the browser protocol is proven.

## Phase 3: Site Archaeology

Do not write business logic until every planned feature has a verified browser-side call. Follow `references/site-exploration.md` to identify:

- the page and login state required;
- DOM selectors or network endpoint;
- required request headers/body;
- response shape and error behavior;
- a working OpenBridge `browser_evaluate` expression.

## Phase 4: Implement

Implement in this order:

1. project scaffold — `references/go-layout.md` for Go;
2. `login-status`, when authentication is required — `references/login-handling.md`;
3. read-only commands;
4. write commands only after read paths work.

Use the repository's OpenBridge compatibility adapter rather than calling the legacy WebBridge protocol. The adapter preserves logical CLI sessions, adopts an existing Chrome tab, honors `OPENBRIDGE_URL`, decodes structured OpenBridge errors, and polls asynchronous JavaScript because OpenBridge's raw `browser_evaluate` response does not await Promises.

After each command:

```bash
{platform}-cli {command} --help
{platform}-cli {command} [args]
```

Contract for every language:

- `--help` / `-h` works on every command;
- success: `{"ok": true, "data": ...}`;
- failure: `{"ok": false, "error": {"code": "...", "message": "..."}}`;
- non-zero exit code on failure.

## Phase 5: Companion Skill

After verification, create `~/.claude/skills/{platform}-cli/SKILL.md` from `references/companion-skill-template.md`. It should teach future agents how to use the CLI, not repeat its implementation.
