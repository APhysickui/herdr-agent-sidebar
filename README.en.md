# Herdr Agent Sidebar

**See what each agent is doing, alongside its stable pane ID.**

[中文文档](README.md)

A community workflow for [Herdr](https://herdr.dev): three-line agent rows, task labels, readable directories, event-based refresh, and an optional macOS timer. Includes Pi task labels and an opt-in Kimi Code compatibility hook.

```text
● Review equations
  codex · w1:p1 · working
  papers / draft

○ Reproduce attention kernel
  pi · w1:p2 · idle
  research / attention
```

## Install

Requires Python 3.11+ and Herdr on your PATH.

```sh
git clone https://github.com/APhysickui/herdr-agent-sidebar.git
cd herdr-agent-sidebar
python3 install.py --with-pi --auto-tabs --dry-run
python3 install.py --with-pi --auto-tabs
```

Use `--with-kimi` only for the documented `kimi-co` recognition problem. The installer refuses to mix its compatibility hook with existing official Herdr/Kimi hooks. Read [troubleshooting](docs/troubleshooting.md) before migrating.

Tested live on macOS with Herdr 0.8.2 and Kimi Code 2.1.1. Linux supports the event plugin and file installation; automatic timer setup currently targets macOS only. CI validates Python logic and isolated install/uninstall on Linux and macOS.

## Behavior

- Stable pane IDs are addresses; task labels can change.
- Manual pane names win. Use `herdr pane rename ID --clear` to return to automatic labels.
- Pi labels use a shortened substantive user request. Existing sessions are matched using visible assistant text, not file recency alone. A Pi extension publishes new requests directly once loaded.
- Generic launcher titles such as `codex resume` fall back to the working directory.
- Persistent event subscriptions coalesce updates for 250ms; local sessions have a two-second fallback. `--auto-tabs` synchronizes tab names and preserves subsequent manual renames.
- Default mode makes no model calls. Optional task summarization must be explicitly configured; it sends only the latest task and limited project context to the selected provider and caches generated titles.

```sh
herdr plugin action invoke community.agent-sidebar.refresh
python3 install.py --uninstall --dry-run
python3 install.py --uninstall
```

Installation resolves local paths, preserves unrelated TOML settings and saves protected backups. Uninstall stops if managed files changed afterward, allowing you to reconcile edits first.

## Development

```sh
PYTHONPATH=plugin python3 -m unittest discover -s tests -v
python3 -m compileall -q install.py plugin
```

See [installation](docs/installation.md), [configuration](docs/configuration.md), [architecture](docs/architecture.md), and [troubleshooting](docs/troubleshooting.md). Apache-2.0; acknowledgements in [NOTICE](NOTICE).
