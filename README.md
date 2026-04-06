# Graph Tree Generator for LLMs

A tree-sitter-based static analysis tool that extracts structural graphs from codebases, stores them in a SQLite database with vector embeddings, and exposes them as MCP tools for Claude.

It parses source files into ASTs and produces a graph of **nodes** (files, functions, classes, calls, exports, types, tables, views) and **edges** (imports, contains, exports, extends, FK relationships) that represent the architecture of a project. The graph is enriched with **source code text** for each node and **vector embeddings** (via Ollama) for semantic similarity search.

The result is a single `.db` file that Claude can query through an MCP server to navigate codebases efficiently -- structural graph traversal for "where is it?" and vector search for "what does it do?" -- reducing token consumption by replacing blind file exploration with targeted O(1) lookups.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
  - [Global Config File](#global-config-file)
  - [DDL Targets](#ddl-targets)
  - [JS/TS Targets](#jsts-targets)
- [Extractor Pipeline](#extractor-pipeline)
- [Label Patterns](#label-patterns)
  - [How Patterns Work](#how-patterns-work)
  - [Recommended Patterns by Project Type](#recommended-patterns-by-project-type)
- [Output Format](#output-format)
- [Alias Resolution](#alias-resolution)
- [Troubleshooting](#troubleshooting)
- [Database Pipeline](#database-pipeline)
  - [Pipeline Flow](#pipeline-flow)
  - [Database Configuration](#database-configuration)
  - [SQLite Schema](#sqlite-schema)
  - [Source Text Capture](#source-text-capture)
- [Embeddings](#embeddings)
  - [Ollama Setup](#ollama-setup)
  - [Embedding Configuration](#embedding-configuration)
  - [How Embeddings Work](#how-embeddings-work)
- [Query CLI](#query-cli)
  - [Commands Reference](#commands-reference)
  - [Query Examples](#query-examples)
- [MCP Server (Claude Integration)](#mcp-server-claude-integration)
  - [Setup](#mcp-setup)
  - [Available Tools](#available-tools)
  - [Claude Workflow](#claude-workflow)
  - [Tool Reference](#tool-reference)

---

## Requirements

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/) (package manager)

Optional (for embeddings):

- [Ollama](https://ollama.ai/) installed and running locally

Dependencies (installed automatically by `uv`):

| Package | Purpose |
|---------|---------|
| `tree-sitter` | Core AST parsing engine |
| `tree-sitter-javascript` | JavaScript grammar (.js, .jsx, .mjs, .cjs) |
| `tree-sitter-typescript` | TypeScript grammar (.ts, .tsx, .mts) |
| `sqlglot` | DDL/SQL parsing for the database extractor |
| `sqlite-vec` | Vector similarity search extension for SQLite |
| `mcp` | Model Context Protocol SDK for Claude integration |

## Installation

```bash
# From the workspace root
uv sync
```

## Quick Start

```bash
# Full pipeline: extract graphs + load into SQLite + generate embeddings
uv run python main.py

# Run a specific target by name
uv run python main.py --target hub4retail-backend

# Skip embeddings (graph + database only, no Ollama needed)
uv run python main.py --no-embeddings

# Use a custom config file
uv run python main.py path/to/my-config.json

# Query the database interactively
uv run python query.py search "authentication login"
uv run python query.py find --type function --name login
uv run python query.py neighbors "table::product"

# Start the MCP server for Claude integration
uv run python mcp_server.py
```

Default config path: `graph_tree_generator/config/config.json`

---

## Configuration Reference

### Global Config File

The config file is a JSON document with top-level settings and a `targets` array. Each target defines one extraction job.

```json
{
  "version": 1,
  "ollama": {
    "url": "http://localhost:11434",
    "model": "nomic-embed-text"
  },
  "database": {
    "path": "graph/code_graph.db"
  },
  "targets": [
    { "type": "ddl",        "name": "...", ... },
    { "type": "javascript", "name": "...", ... },
    { "type": "typescript", "name": "...", ... }
  ]
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ollama.url` | string | `"http://localhost:11434"` | Ollama API endpoint |
| `ollama.model` | string | `"nomic-embed-text"` | Embedding model name (must be an embedding model, not generative) |
| `database.path` | string | `"graph/code_graph.db"` | SQLite database output path (relative to workspace root or absolute) |

You can also pass a single-target JSON file directly (legacy format) — the tool auto-detects it.

---

### DDL Targets

Extract a graph of tables, columns, foreign keys, indexes, views, and enums from a SQL DDL file.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"ddl"` | yes | Extractor type |
| `name` | string | yes | Target name (used in logs and `--target` filtering) |
| `file` | string | yes | Path to the DDL file (relative to workspace root, or absolute) |
| `dialect` | string | no | SQL dialect (`"postgres"` default) |
| `output` | string | no | Output path, relative to workspace root |

**Example:**

```json
{
  "type": "ddl",
  "name": "hub4retail-db",
  "file": "ddl/tables/FULL_DB_DDL.sql",
  "dialect": "postgres",
  "output": "graph/db_graph.json"
}
```

---

### JS/TS Targets

Extract a structural graph from a JavaScript or TypeScript codebase. This is the main extractor and has the most configuration options.

#### Top-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"javascript"` \| `"typescript"` | yes | — | Language grammar to use. `"typescript"` auto-selects `.ts`/`.tsx` grammars |
| `name` | string | yes | — | Target name |
| `root` | string | yes | — | Path to project root (relative to workspace root, or absolute) |
| `output` | string | no | `graph/<name>_graph.json` | Output file path |
| `include` | string[] | yes | — | Glob patterns for files to scan (relative to `root`) |
| `exclude` | string[] | no | `["**/node_modules/**"]` | Glob patterns for files to skip |
| `max_depth` | int \| null | no | `null` (unlimited) | Max directory depth from `root` |

#### `extract` — What to extract

Controls which AST visitors run. Disable visitors you don't need to reduce output size and speed up extraction.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `imports` | bool | `true` | ESM `import` statements and CJS `require()` calls |
| `exports` | bool | `true` | ESM `export` and CJS `module.exports` |
| `functions` | bool | `true` | Function declarations, arrow functions, methods |
| `calls` | bool | `true` | All call expressions (function calls, method calls, `new`) |
| `classes` | bool | `true` | Class declarations with methods and properties |
| `types` | bool | `false` | TypeScript interfaces, type aliases, enums (TS files only) |

#### `resolve` — Import resolution

Controls how import specifiers are resolved to project-relative file paths, which determines the **edges** in the graph.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `extensions` | string[] | `[".js", ".ts", ".tsx", ".jsx", "/index.js", "/index.ts"]` | File extensions to try when resolving bare imports. Entries starting with `/` are treated as directory index files |
| `tsconfig` | string \| null | `null` | Path to `tsconfig.json` relative to `root`. If set, reads `baseUrl` and `paths` for resolution |
| `alias` | object | `{}` | Manual alias map: `{ "prefix": "target/path" }`. Overrides tsconfig |
| `skip_external` | bool | `true` | Skip `node_modules` / third-party imports (return `null`) |

#### `labels` — Semantic call labeling

Labels are pattern rules applied to call expressions. When a call's flattened callee chain matches a pattern, the call node in the output graph gets tagged with a label. This is how you mark calls as "HTTP routes", "API calls", "auth checks", etc.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pattern` | string | yes | One or more `fnmatch` glob patterns, separated by `\|` |
| `label` | string | yes | Semantic label to apply to matching calls |
| `capture_arg` | int \| null | no | If set, captures the Nth argument (0-indexed) as a string value |

Full configuration details in [Label Patterns](#label-patterns) below.

---

## Extractor Pipeline

The JS/TS extractor processes files through this pipeline:

```
┌─────────────┐
│  config.json │
└──────┬──────┘
       │
  1. SCAN         discover_files() — apply include/exclude globs, max_depth
       │
  2. PARSE        tree-sitter parse — select grammar by file extension
       │               .js/.jsx/.mjs/.cjs  →  JavaScript grammar
       │               .ts/.mts            →  TypeScript grammar
       │               .tsx                →  TSX grammar
       │
  3. VISIT        Run enabled visitors on each file's AST:
       │               imports  → ImportInfo[]     (ESM + CJS)
       │               exports  → ExportInfo[]     (ESM + CJS)
       │               functions→ FunctionInfo[]   (declarations, arrows, methods)
       │               calls    → CallInfo[]       (all call expressions)
       │               classes  → ClassInfo[]      (with methods + properties)
       │               types    → TypeInfo[]       (interfaces, type aliases, enums)
       │
  4. RESOLVE      ImportResolver maps each import specifier to a project-relative
       │          file path using: relative paths → aliases → tsconfig paths →
       │          baseUrl → skip external
       │
  5. LABEL        apply_labels() matches each call's callee chain against label
       │          rules using fnmatch. Adds labels[] and captured_arg to CallInfo.
       │
  6. BUILD        graph_builder assembles all FileResults into a single
       │          { metadata, nodes[], edges[] } JSON graph.
       │
  7. WRITE        Output to the configured .json file
```

---

## Label Patterns

Labels are the most powerful configuration feature. They turn raw call expressions into semantically meaningful markers — allowing you to query "which files make API calls?" or "where are auth checks?" from the output graph.

### How Patterns Work

Each call expression in the AST gets its callee **flattened** into a dot-separated chain:

| Source code | Flattened callee |
|-------------|-----------------|
| `foo()` | `foo` |
| `router.get(...)` | `router.get` |
| `this.service.findAll(...)` | `this.service.findAll` |
| `connectorHandler.connector.find_items(...)` | `connectorHandler.connector.find_items` |
| `axios.get(...)` | `axios.get` |
| `useReducer(...)` | `useReducer` |
| `dispatch({ type: ... })` | `dispatch` |

Patterns use Python's `fnmatch` syntax (same as shell globbing):

| Pattern | Matches |
|---------|---------|
| `foo` | Exactly `foo` |
| `*.get` | Anything ending in `.get` (e.g. `router.get`, `axios.get`, `http.get`) |
| `*_router.get` | Any variable ending in `_router` followed by `.get` |
| `*.connector.find_*` | Any connector call starting with `find_` |
| `useReducer` | Exactly `useReducer` |
| `use*` | Any call starting with `use` (matches all React hooks) |

Multiple patterns can be combined with `|` (pipe):

```json
{
  "pattern": "*.get|*.post|*.put|*.delete|*.patch",
  "label": "http_call"
}
```

### `capture_arg`

When set, the labeler captures the string value of the Nth argument (0-indexed) from the call's argument preview. Useful for extracting route paths, event names, etc.

```json
{
  "pattern": "*_router.get|*_router.post",
  "label": "http_route",
  "capture_arg": 0
}
```

Given `product_router.get("/api/products", ...)`, this produces:

```json
{
  "callee": "product_router.get",
  "labels": ["http_route"],
  "captured_arg": "/api/products"
}
```

---

### Recommended Patterns by Project Type

#### Express/Node.js Backend (CommonJS)

These patterns target the Hub4Retail backend architecture: Route-Interface-Service layers, connector ORM calls, permission checks.

```json
"labels": [
  {
    "pattern": "*_router.get|*_router.post|*_router.put|*_router.delete|*_router.patch",
    "label": "http_route",
    "capture_arg": 0
  },
  {
    "pattern": "*.connector.find_item|*.connector.find_items|*.connector.find_all_items|*.connector.findAndCount|*.connector.count|*.connector.new_item|*.connector.new_items|*.connector.update_items|*.connector.bulk_update|*.connector.delete_items|*.connector.batch_delete|*.connector.raw_query",
    "label": "db_access"
  },
  {
    "pattern": "*.checkPermissions",
    "label": "auth_check"
  }
]
```

| Label | Why it matters |
|-------|---------------|
| `http_route` | Maps every HTTP endpoint with its path. Essential for API surface discovery and contract validation. `capture_arg: 0` extracts the route string (e.g. `"/api/v1/products"`). |
| `db_access` | Marks every ORM call through the connector handler. Reveals which modules touch which tables, identifies N+1 patterns, and supports impact analysis when changing schema. |
| `auth_check` | Tags permission checks. Allows you to verify that every route has an auth guard — any route without an `auth_check` label in its call tree is a potential security gap. |

**When to add more backend labels:**

- `"pattern": "*.sendMail|*.send_email", "label": "email"` — if your service sends emails
- `"pattern": "s3.putObject|s3.getObject|s3.deleteObject", "label": "s3_access"` — for AWS S3 interactions
- `"pattern": "*.publish|*.emit", "label": "event_emit"` — for event/message publishing

---

#### React + TypeScript Frontend (ESM)

These patterns target a modern React codebase using Context API + useReducer, React Router, i18next, axios, and Auth0.

```json
"labels": [
  {
    "pattern": "useReducer",
    "label": "state_management"
  },
  {
    "pattern": "createContext",
    "label": "context_provider"
  },
  {
    "pattern": "useContext",
    "label": "context_consumer"
  },
  {
    "pattern": "useState",
    "label": "local_state"
  },
  {
    "pattern": "useEffect",
    "label": "side_effect"
  },
  {
    "pattern": "useMemo|useCallback",
    "label": "memoization"
  },
  {
    "pattern": "useNavigate|useParams|useLocation|useSearchParams",
    "label": "routing"
  },
  {
    "pattern": "useTranslation",
    "label": "i18n"
  },
  {
    "pattern": "axios.get|axios.post|axios.put|axios.delete|axios.patch",
    "label": "api_call",
    "capture_arg": 0
  },
  {
    "pattern": "useAuth0|*.loginWithRedirect|*.logout|*.getAccessTokenSilently",
    "label": "auth"
  },
  {
    "pattern": "lazy",
    "label": "lazy_load"
  },
  {
    "pattern": "dispatch",
    "label": "dispatch"
  }
]
```

| Label | Why it matters |
|-------|---------------|
| `state_management` | Marks files that create useReducer stores — the core of each context domain. Instantly maps which features have complex state vs simple local state. |
| `context_provider` | Identifies where `createContext()` is called — these are the root files of each context domain (the 5-file pattern). Lets you enumerate all domains programmatically. |
| `context_consumer` | Shows which components consume which contexts via `useContext()`. Reveals coupling between components and state domains. |
| `local_state` | Tags `useState` calls. Distinguishes components with local UI state from those that depend on shared context. High `local_state` + no `context_consumer` = pure UI component. |
| `side_effect` | Marks `useEffect` calls — data fetching, subscriptions, DOM manipulation. Files with many side effects are more complex and harder to test. |
| `memoization` | Tags `useMemo`/`useCallback`. Highlights performance-sensitive components. Useful when profiling or auditing unnecessary memoization. |
| `routing` | Tags React Router hook usage. Maps which components depend on URL state, helping you understand the routing layer without reading every file. |
| `i18n` | Marks translated components. Useful when checking i18n coverage or finding untranslated components. |
| `api_call` | The most important frontend label. Tags every HTTP call with the URL (`capture_arg: 0`). Maps the frontend-to-backend communication surface — essential for contract validation and impact analysis. |
| `auth` | Tags Auth0 interactions. Shows which components trigger login flows, token refresh, or read user identity. |
| `lazy_load` | Marks `React.lazy()` calls. Maps which routes/components are code-split, useful for bundle analysis. |
| `dispatch` | Tags reducer dispatch calls. Shows which components trigger state changes, revealing the write-side of your state architecture. |

**Tuning `api_call` precision:**

The `axios.get|axios.post|...` pattern only matches calls on a variable literally named `axios`. If your project wraps axios in a custom instance (common pattern), you need to match that name instead:

```typescript
// src/api/httpClient.ts
const httpClient = axios.create({ baseURL: '...' });
export default httpClient;

// src/api/products.ts
import httpClient from './httpClient';
httpClient.get('/products');  // callee = "httpClient.get"
```

For this pattern, use:

```json
{
  "pattern": "httpClient.get|httpClient.post|httpClient.put|httpClient.delete|httpClient.patch",
  "label": "api_call",
  "capture_arg": 0
}
```

To find the right name, search for `axios.create` in your codebase:

```bash
grep -r "axios.create" src/api/ --include="*.ts"
```

**When to add more frontend labels:**

- `"pattern": "useForm|useWatch|useFieldArray", "label": "form"` — for React Hook Form usage
- `"pattern": "notification.*|message.*", "label": "user_notification"` — for Ant Design notifications
- `"pattern": "console.log|console.warn|console.error", "label": "console_log"` — to find debug logging left in code

---

#### Generic TypeScript Library / Utility Package

For non-React, non-Express TypeScript projects (shared libs, CLIs, SDKs):

```json
"labels": [
  {
    "pattern": "console.log|console.warn|console.error|console.debug",
    "label": "logging"
  },
  {
    "pattern": "throw|reject",
    "label": "error_boundary"
  },
  {
    "pattern": "fs.*|readFile*|writeFile*",
    "label": "filesystem"
  },
  {
    "pattern": "*.on|*.once|*.emit|*.addEventListener",
    "label": "event"
  }
]
```

---

## Output Format

The extractor produces a single JSON file with this structure:

```json
{
  "metadata": {
    "extracted_at": "2026-04-04T12:18:12.172859",
    "project": "hub4retail-backend",
    "project_root": "/path/to/project",
    "total_files": 294,
    "total_functions": 1616,
    "total_classes": 169,
    "total_calls": 12140,
    "total_labeled_calls": 1488,
    "total_nodes": 14510,
    "total_edges": 2989
  },
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

### Node Types

| Type | ID format | Key fields |
|------|-----------|------------|
| `file` | `file::<path>` | `path` |
| `function` | `func::<path>::<qualified_name>` | `name`, `kind` (declaration/arrow/method/generator), `async`, `params`, `enclosing_class`, `source_text` |
| `class` | `class::<path>::<name>` | `name`, `extends`, `methods[]`, `properties[]`, `source_text` |
| `call` | `call::<path>::L<line>::<callee>` | `callee`, `args_preview`, `is_new`, `labels[]`, `captured_arg` |
| `export` | `export::<path>::<name>` | `name`, `kind` (function/class/variable/re-export), `value_hint` |
| `interface` | `type::<path>::<name>` | `name`, `kind="interface"`, `members[]`, `extends[]`, `source_text` |
| `type_alias` | `type::<path>::<name>` | `name`, `kind="type_alias"`, `source_text` |
| `enum` | `type::<path>::<name>` | `name`, `kind="enum"`, `members[]`, `source_text` |

### Edge Types

| Type | From | To | Description |
|------|------|----|-------------|
| `imports` | file | file (or null) | File imports another. `to` is null for unresolved/external modules |
| `exports` | file | export | File exports a binding |
| `contains` | file | function/class | File contains a function or class definition |
| `extends` | class | null | Class extends another (target resolved by name, not file) |

---

## Alias Resolution

Import resolution follows this priority order:

1. **Relative imports** (`./foo`, `../bar`) — resolved from the importing file's directory
2. **Manual aliases** (`resolve.alias` in config) — prefix matching, highest priority for non-relative
3. **tsconfig `paths`** — glob-based path mapping from tsconfig.json
4. **tsconfig `baseUrl`** — resolve non-relative imports from the base directory
5. **External** — if `skip_external` is true (default), returns `null`

For each candidate, the resolver tries appending each extension from `resolve.extensions` in order:

```json
"extensions": [".ts", ".tsx", "/index.ts", "/index.tsx"]
```

Entries starting with `/` try a directory index (e.g., `foo/` → `foo/index.ts`).

### Example: Vite aliases

If your `vite.config.ts` has:

```typescript
resolve: {
  alias: {
    api: path.resolve(__dirname, 'src/api'),
    contexts: path.resolve(__dirname, 'src/contexts'),
  }
}
```

Mirror them in the extractor config:

```json
"resolve": {
  "alias": {
    "api": "src/api",
    "contexts": "src/contexts"
  }
}
```

The alias values are **relative to the project `root`**, not the workspace root.

### Example: tsconfig baseUrl

If your `tsconfig.json` has `"baseUrl": "src"`, instead of manually listing every directory as an alias, you can point to the tsconfig:

```json
"resolve": {
  "tsconfig": "tsconfig.json"
}
```

The resolver reads `baseUrl` and `paths` from it automatically. Note: if both `alias` (manual) and `tsconfig` paths match, the manual alias takes priority.

---

## Troubleshooting

### "No files found"

- Check that `root` points to the right directory (relative to workspace root, not config file)
- Verify your `include` globs match actual files. Test with: `ls services/frontend/hub4retail-brand/src/**/*.tsx`
- Check that `exclude` patterns aren't filtering everything out

### Missing import edges (many `null` targets)

- Add path aliases to `resolve.alias` — bare imports like `import X from 'contexts/...'` won't resolve without them
- Add directory index extensions: `"/index.ts"`, `"/index.tsx"` to `resolve.extensions`
- Set `resolve.tsconfig` if the project uses `baseUrl` or `paths`

### Excessive output size

- Disable visitors you don't need (e.g., `classes: false` for React frontends)
- Narrow `include` patterns (e.g., `src/contexts/**/*.ts` instead of `src/**/*.ts`)
- Add more `exclude` patterns for generated or vendored files

### Labels not matching

- Check the flattened callee format. Add a temporary `"pattern": "*", "label": "debug"` rule to see all callee strings in the output, then remove it
- Remember that `fnmatch` `*` does NOT match dots in some contexts — `*.get` matches `router.get` but `*` alone matches `router` not `router.get`. Use `*.*` or be explicit

### Tree-sitter parse errors

- Ensure the `type` field matches the actual language. Use `"typescript"` for `.ts`/`.tsx` files, `"javascript"` for `.js`
- Files with syntax errors still produce partial ASTs — extraction continues with best-effort results
- Errors are collected and reported at the end (first 10 shown)

---

## Database Pipeline

The pipeline extends the graph extractor with a SQLite database and vector embeddings, creating a queryable code knowledge base.

### Pipeline Flow

```
uv run python main.py
```

```
1. CHECK OLLAMA      Is Ollama running? Is the embedding model available?
       |             If model missing, auto-pull it. If Ollama unreachable, skip embeddings.
       |
2. VALIDATE          Load targets from config. Check that root dirs / DDL files exist.
       |             Skip targets with missing paths.
       |
3. EXTRACT           For each target, run tree-sitter (JS/TS) or sqlglot (DDL).
       |             Produce graph JSON with source_text captured per node.
       |             JSON files still written to graph/ for inspection.
       |
4. DATABASE          Delete existing DB. Create fresh SQLite with schema.
       |             Load all graphs: normalize DDL into nodes/edges format,
       |             insert JS/TS nodes/edges directly.
       |
5. EMBED             For every node with source_text, generate a 768-dim vector
       |             via Ollama and store in sqlite-vec virtual table.
       |
  OUTPUT             graph/code_graph.db  (single file, zero infrastructure)
```

Every run is a **full refresh** — the database is recreated from scratch. This keeps the pipeline simple and the data always consistent with the current state of the source code.

### Database Configuration

In `config.json`:

```json
{
  "database": {
    "path": "graph/code_graph.db"
  }
}
```

The path can be relative (to workspace root) or absolute.

CLI flags:

```bash
uv run python main.py                    # full pipeline (extract + DB + embeddings)
uv run python main.py --no-embeddings    # skip embedding generation
uv run python main.py --target my-app    # only process specific target(s)
```

### SQLite Schema

The database has 5 tables:

```sql
-- One row per extraction target (backend, frontend, DDL, etc.)
targets (name TEXT PK, type, root, extracted_at, metadata JSON)

-- All graph nodes normalized into a flat table
nodes (id TEXT, target TEXT, type, file, line, name, source_text, properties JSON)
  -- PK: (id, target)
  -- Indexes: (type, target), (file), (name)

-- All graph edges
edges (source, target_node, type, target, properties JSON)
  -- Indexes: (source, target), (target_node, target), (type, target)

-- Cross-target references (for future use)
cross_references (source_node, source_target, target_node, target_target, type, confidence)

-- Vector similarity search (sqlite-vec)
vec_embeddings (node_id TEXT PK, target TEXT, embedding FLOAT[768])
```

**Node types in the database:**

| Type | Source | Description |
|------|--------|-------------|
| `file` | JS/TS | Source file |
| `function` | JS/TS | Function/method/arrow with source code |
| `class` | JS/TS | Class definition with source code |
| `call` | JS/TS | Call expression with labels |
| `export` | JS/TS | Exported binding |
| `interface` | TS | TypeScript interface with source code |
| `type_alias` | TS | TypeScript type alias with source code |
| `enum` | TS/DDL | TypeScript or PostgreSQL enum |
| `table` | DDL | Database table with columns, PKs, FKs |
| `view` | DDL | Regular view |
| `materialized_view` | DDL | Materialized view |

**Edge types in the database:**

| Type | Description |
|------|-------------|
| `imports` | File imports another file |
| `exports` | File exports a binding |
| `contains` | File contains a function/class |
| `extends` | Class extends another |
| `fk` | Foreign key relationship between tables |
| `depends_on` | View depends on a table/view |

### Source Text Capture

The extractors capture actual source code for nodes that benefit from semantic search:

| Node type | What is captured | Max length |
|-----------|-----------------|------------|
| `function` | Full function body (signature + implementation) | 2000 chars |
| `class` | Full class definition (including methods) | 2000 chars |
| `interface` | Interface declaration with all members | 2000 chars |
| `type_alias` | Type alias declaration | 2000 chars |
| `enum` | Enum declaration with members | 2000 chars |
| `table` (DDL) | Structured description: columns, types, PKs, FKs | N/A |
| `view` (DDL) | Structured description: columns, sources, definition preview | N/A |

Nodes without source text (files, calls, exports, edges) are not embedded but are still queryable through the graph.

---

## Embeddings

### Ollama Setup

The pipeline uses [Ollama](https://ollama.ai/) to run embedding models locally. No API keys or external services required.

```bash
# Install Ollama (https://ollama.ai/download)
# Then pull an embedding model:
ollama pull nomic-embed-text
```

The pipeline auto-pulls the configured model if it's not present, so manual pulling is optional.

**Important:** Use an **embedding model**, not a generative model. Embedding models are small (100-300M params), fast, and produce fixed-dimension vectors. Generative models (Qwen, Llama, etc.) are for text generation and cannot produce useful embeddings.

Recommended embedding models:

| Model | Params | Dimensions | Notes |
|-------|--------|------------|-------|
| `nomic-embed-text` | 137M | 768 | Good default, fast |
| `nomic-embed-text-v2-moe` | — | 768 | Newer MoE variant |
| `mxbai-embed-large` | 335M | 1024 | Higher quality, slower |

If using a model with dimensions other than 768, update the `FLOAT[768]` in `graph_tree_generator/db/schema.py` to match.

### Embedding Configuration

In `config.json`:

```json
{
  "ollama": {
    "url": "http://localhost:11434",
    "model": "nomic-embed-text"
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `url` | `http://localhost:11434` | Ollama API endpoint |
| `model` | `nomic-embed-text` | Embedding model to use |

### How Embeddings Work

1. The pipeline selects all nodes with non-empty `source_text` from the database
2. Texts are sent to Ollama in batches of 32 via the `/api/embed` endpoint
3. Each returned 768-dimension vector is stored in the `vec_embeddings` virtual table
4. At query time, a search query is embedded with the same model, then sqlite-vec finds the nearest vectors using cosine distance

This enables natural language queries like "find code that handles user authentication" to return the most semantically relevant functions, classes, and types across the entire codebase.

---

## Query CLI

`query.py` provides an interactive command-line interface for exploring the database.

### Commands Reference

```bash
uv run python query.py <command> [options]
```

| Command | Description |
|---------|-------------|
| `stats` | Database overview: targets, node/edge counts, embedding stats |
| `search <query>` | Semantic similarity search using natural language |
| `find` | Find nodes by type, name, file pattern, or semantic label |
| `node <id>` | Look up a specific node by ID (full or partial match) |
| `neighbors <id>` | Graph traversal: show all edges in/out of a node |
| `context <query>` | Semantic search + expand graph neighbors around results |
| `tables` | List all DDL tables with columns |
| `sql <query>` | Run a raw SQL query against the database |

### Query Examples

**Semantic search** — find code by meaning:

```bash
# Find authentication-related code
uv run python query.py search "user authentication login permissions"

# Search only in the backend
uv run python query.py search "database connection pooling" --target hub4retail-backend

# Find product catalog logic
uv run python query.py search "product catalog pricing" --limit 5
```

**Structured lookup** — find nodes by attributes:

```bash
# All functions named "login" across all targets
uv run python query.py find --type function --name login

# All HTTP route calls in the backend
uv run python query.py find --type call --label http_route --target hub4retail-backend

# All tables with "product" in the name
uv run python query.py find --type table --name product

# All functions in a specific file
uv run python query.py find --type function --file "user.actions.ts"
```

**Node detail** — read source code:

```bash
# Full details of a specific function
uv run python query.py node "func::applications/main/interface/user.js::User.login"

# Partial match works too
uv run python query.py node "User.login"
```

**Graph traversal** — explore relationships:

```bash
# What tables does the product table reference? What references it?
uv run python query.py neighbors "table::product"

# What does a specific file contain/import?
uv run python query.py neighbors "file::applications/main/interface/user.js"
```

**Context search** — semantic search + structural context:

```bash
# Find order processing code and show what it connects to
uv run python query.py context "database access for orders" --limit 3
```

**Raw SQL** — for anything custom:

```bash
# Count functions per target
uv run python query.py sql "SELECT target, COUNT(*) FROM nodes WHERE type='function' GROUP BY target"

# Find all db_access labeled calls
uv run python query.py sql "SELECT name, file, line FROM nodes WHERE properties LIKE '%db_access%' LIMIT 20"

# Tables with the most foreign key references
uv run python query.py sql "SELECT target_node, COUNT(*) as refs FROM edges WHERE type='fk' GROUP BY target_node ORDER BY refs DESC LIMIT 10"
```

---

## MCP Server (Claude Integration)

The MCP (Model Context Protocol) server exposes the code graph as tools that Claude can call directly. This is the key integration that allows Claude to navigate large codebases efficiently.

<a name="mcp-setup"></a>
### Setup

**1. Add to Claude Code settings**

Add the server to your MCP configuration. For project-level config, create or edit `.claude/settings.local.json` in the project where you want to use the tools:

```json
{
  "mcpServers": {
    "code-graph": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Repositories/MyProjects/Backend/Projects_graph_generator", "python", "mcp_server.py"]
    }
  }
}
```

For global config, add to `~/.claude/settings.json` instead.

**2. Verify it works**

After restarting Claude Code, the tools should appear. You can verify by asking Claude: "What tools do you have from code-graph?"

**Prerequisites:**
- The database must exist (`uv run python main.py` must have been run at least once)
- For semantic search tools, Ollama must be running with the configured model

### Available Tools

| Tool | Purpose | When to use |
|------|---------|-------------|
| `graph_overview` | Database stats: targets, node/edge counts, types | First call — understand what's available |
| `search_code` | Semantic similarity search by natural language | "Find code related to X" — broad discovery |
| `find_nodes` | Structured lookup by type, name, file, label | When you know what you're looking for |
| `get_node_detail` | Full node info including source code text | Read the actual implementation |
| `get_neighbors` | Graph traversal: edges in/out of a node | Understand structural relationships |
| `trace_path` | BFS path finding between two nodes (up to 5 hops) | How does A connect to B? |
| `get_table_schema` | DDL table details: columns, PKs, FKs, related tables | Database schema exploration |

### Claude Workflow

The recommended workflow for Claude when answering code questions:

```
1. graph_overview()              -- What targets/types are in the DB?
       |
2. search_code("user auth")     -- Semantic search: find relevant code
       |
3. get_node_detail(node_id)     -- Read the actual source code
       |
4. get_neighbors(node_id)       -- What does it connect to? (imports, calls, contains)
       |
5. trace_path(from, to)         -- How do two pieces of code relate?
```

This replaces the traditional pattern of:
- Reading entire directories to find relevant files (O(n) tokens)
- Grepping for keywords that may not match semantic intent
- Manually tracing import chains

With:
- Vector search for semantic relevance (O(1) lookup)
- Graph traversal for structural context (targeted reads)
- Reading only the source code that matters

### Tool Reference

#### `search_code`

```
search_code(query: str, limit: int = 10, target: str | None = None) -> JSON
```

Semantic similarity search. Embeds the query with the same model used at build time and finds the nearest code nodes.

**Parameters:**
- `query` — Natural language description ("product pricing calculation", "error handling middleware")
- `limit` — Max results (default 10)
- `target` — Filter to a specific target (e.g. `"hub4retail-backend"`)

**Returns:** Array of matches with `node_id`, `target`, `type`, `name`, `file`, `line`, `distance`, `source_preview`.

#### `find_nodes`

```
find_nodes(type, name, target, file, label, limit) -> JSON
```

Structured lookup. At least one filter required.

**Parameters:**
- `type` — Node type: `function`, `class`, `call`, `table`, `interface`, `export`, etc.
- `name` — Name pattern (use `%` as wildcard)
- `target` — Target name
- `file` — File path pattern (use `%` as wildcard)
- `label` — Semantic label: `http_route`, `db_access`, `auth_check`, `api_call`, etc.
- `limit` — Max results (default 20)

#### `get_node_detail`

```
get_node_detail(node_id: str, target: str | None = None) -> JSON
```

Full node details. Supports partial ID matching — "User.login" will match `func::applications/main/interface/user.js::User.login`.

**Returns:** Full node including `properties` dict and `source_text` (the actual code).

#### `get_neighbors`

```
get_neighbors(node_id: str, target, direction = "both", edge_type = None) -> JSON
```

Graph traversal.

**Parameters:**
- `direction` — `"out"` (outgoing edges), `"in"` (incoming), `"both"`
- `edge_type` — Filter: `imports`, `exports`, `contains`, `fk`, `depends_on`, `extends`

**Returns:** `{ outgoing: [...], incoming: [...] }` with full node info for each neighbor.

#### `trace_path`

```
trace_path(from_node, to_node, from_target, to_target, max_depth = 3) -> JSON
```

BFS path finding between two nodes.

**Returns:** `{ found: bool, hops: int, path: [...] }` with each step showing the node and edge traversed.

#### `get_table_schema`

```
get_table_schema(table_name: str) -> JSON
```

Full DDL table info.

**Returns:** `{ table, columns[], primary_key[], unique_constraints[], references[], referenced_by[] }`

#### `graph_overview`

```
graph_overview() -> JSON
```

Database summary.

**Returns:** `{ targets[], node_counts_by_type, edge_counts_by_type, total_nodes, nodes_with_source_text, nodes_with_embeddings }`
