# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## Current state

This repository is a **blank slate**. It contains only a `README.md`:

> Build a production-ready AI Executive Assistant that works as my personal
> digital chief of staff.

There is no source code, framework, dependency manifest, test suite, or CI
configuration yet. Nothing here should be assumed about language, runtime,
or architecture — none of it has been decided.

## Working in this repo

Because there is no established structure or convention to follow yet, do
not invent a large scaffold speculatively. Instead:

- If asked to start implementing, first clarify scope with the user: what
  the "Executive Assistant" should actually do (e.g. email triage,
  calendar management, task/reminder handling), which integrations it
  needs (the session has MCP access to Gmail, Google Calendar, Google
  Drive, Todoist, Zoom, Canva, Spotify — likely candidates for a "chief of
  staff" tool), and what runtime/language is preferred.
- Once real code lands, update this file to describe the actual structure
  (entry points, module layout, how to run/build/test, and any
  conventions that emerge) rather than the placeholder text above.
- Avoid adding boilerplate, dependencies, or config "for later" — keep
  changes scoped to what's actually being built in each session.

## Git workflow

- Default branch: `main`.
- Repo remote is hosted on GitHub as `Beltass/AI-Executive-Assistant`.
