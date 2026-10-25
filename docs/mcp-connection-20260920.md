# MCP connection notes for 2026-09-20

Connected to the ShunCode Bridge MCP endpoint and initialized protocol `2024-11-05`.

Server:

- Name: `shuncode-bridge`
- Version: `0.7.5`
- Capabilities: tools and logging

Confirmed workspace access with `list_directory` at the repository root. The root contains project areas including `src`, `backend`, `electron`, `extension`, `packages`, `services`, `android`, `tests`, `e2e`, `docs`, and supporting configuration files such as `package.json`, `vite.config.ts`, and `tsconfig.json`.

Operating rules captured from the MCP server:

- Discover files with `list_directory` and `find_files`; search contents with `search_files`.
- Use `lsp` for semantic navigation when locating symbols, definitions, references, implementations, and hover/type information.
- Read files before editing, and prefer batching independent reads/searches.
- Edit via `apply_patch`, using version hashes from `read_files` when available.
- Keep patches focused and reread files after stale or context-mismatch failures.
- Validate meaningful edits with `get_diagnostics` and relevant build/test commands.
- Use `run_command` for shell work on the local Windows host, including locations outside the workspace after read-only discovery.
- For multi-step tasks, maintain durable state with `set_todos` or `update_plan`, keeping at most one item in progress.
- Use `report_progress` for transient status updates during longer work.
- Write analyses, audits, plans, and reviews produced during a session under `docs/` using the `mcp-<topic>.md` naming style.

Available tools summarized:

- `list_directory`: list immediate workspace contents.
- `find_files`: locate files by path/name glob.
- `search_files`: search UTF-8 text contents.
- `read_files`: read one or more workspace text files.
- `read_image`: inspect workspace image assets.
- `lsp`: semantic code navigation.
- `apply_patch`: apply workspace edits.
- `get_diagnostics`: read editor/language-service diagnostics.
- `run_command`: run Bash commands on the Windows host.
- `get_command_output`: inspect running command output.
- `send_command_input`: provide input to an interactive command.
- `cancel_command`: stop a managed command.
- `set_todos`: publish durable task state.
- `update_plan`: compatibility plan updater.
- `report_progress`: publish transient progress.
