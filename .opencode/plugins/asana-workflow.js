import path from "node:path"
import { fileURLToPath } from "node:url"
import { readFileSync } from "node:fs"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pluginsDir = path.resolve(__dirname, "../../plugins/asana-workflow")
const skillsDir = path.resolve(pluginsDir, "skills")

const TOOL_MAPPING = `
## OpenCode Runtime — Tool Mapping

You are running under OpenCode, NOT Claude Code. The following tool names are
mapped from Claude Code conventions to OpenCode equivalents:

| Claude Code Tool | OpenCode Equivalent |
|---|---|
| TodoWrite | todowrite |
| Task (subagents) | @mention syntax for dispatching subagents |
| Skill | native skill tool |
| EnterWorktree | use native git worktree commands directly |

When a skill instructs you to use a Claude Code tool name, translate it to the
corresponding OpenCode tool or workflow.
`

const EXTERNAL_DEPS = `
## External Dependencies

Skills reference external plugins. Handle them as follows under OpenCode:

- **feature-dev@claude-plugins-official**: DOES NOT EXIST under OpenCode.
  When any skill says to invoke \`feature-dev:feature-dev\`, translate that to
  \`superpowers:subagent-driven-development\`.

- **superpowers**: REQUIRED. It must be installed alongside asana-workflow in
  opencode.json. Invoke its skills normally via the native skill tool. If it is
  absent, stop and tell the user to run \`bash setup.sh --opencode\`.

- **MCP servers**: REQUIRED. mobile-mcp and chrome-devtools are declared by
  this plugin (.mcp.json) and registered automatically when the plugin loads.
  If a QA skill needs one and it is unavailable, stop and tell the user to
  restart OpenCode (or re-run \`bash setup.sh --opencode\`).

When a skill references /plugin install or /plugin reload commands, those are
Claude Code-specific plugin management commands. Under OpenCode, dependencies
are managed via opencode.json and setup.sh.
`

const CLAUDE_MD_MAPPING = `
## Project Config File

When a skill instructs you to read CLAUDE.md, also check for AGENTS.md and
opencode.json. If AGENTS.md exists, prefer it. CLAUDE.md may contain
Claude Code-specific configuration that does not apply.
`

const SKILL_PATHS = `
## Skill File Resolution

The asana-workflow plugin root is at: ${pluginsDir}

Skills live at: ${skillsDir}

When a skill instructs you to read a reference file, resolve paths as follows:

- Paths starting with \`plugins/asana-workflow/\` are relative to the
  repository root. The plugin root maps to \`${pluginsDir}/\`.
- Relative paths like \`references/xxx.md\` are relative to the current
  skill's own directory (e.g. \`.../skills/start-task/references/xxx.md\`).
- State files (checkpoints, board cache) are at: ~/.cortex/asana-workflow/

When reading a skill's reference files, use the absolute filesystem path
shown above — do NOT guess paths relative to your current working directory.
`

const BOOTSTRAP = [
  TOOL_MAPPING,
  EXTERNAL_DEPS,
  CLAUDE_MD_MAPPING,
  SKILL_PATHS,
].join("\n")

let _bootstrapCache = null

function getBootstrap() {
  if (_bootstrapCache) return _bootstrapCache
  _bootstrapCache = `<EXTREMELY_IMPORTANT>
You are running the asana-workflow plugin under OpenCode.

Skills are available from the asana-workflow plugin. Use the native skill tool
to list them and load as needed. Key entry points:

- **start-task**: Orchestrates the full development lifecycle from an Asana task URL
- **ship-it**: Shipping orchestrator (PR promotion, Asana status, work summary)
- **log-task**: Create Asana tasks from conversation-discovered work

State files are stored in ~/.cortex/asana-workflow/.

${BOOTSTRAP}
</EXTREMELY_IMPORTANT>`
  return _bootstrapCache
}

export const AsanaWorkflowPlugin = async () => {
  return {
    config: async (config) => {
      if (!config.skills) config.skills = { paths: [] }
      if (!config.skills.paths) config.skills.paths = []
      config.skills.paths.push(skillsDir)

      if (!config.permission) config.permission = {}
      if (!config.permission.external_directory) config.permission.external_directory = {}
      // Whitelist paths the plugin needs to read/write outside the project directory
      config.permission.external_directory["~/.cortex/asana-workflow/*"] = "allow"
      // ^ checkpoint files and board registry cache (written by checkpoint.sh, read by skills)
      config.permission.external_directory["~/.config/opencode/opencode.json"] = "allow"
      // ^ dependency check reads opencode.json to verify superpowers is installed
      config.permission.external_directory[`${pluginsDir}/*`] = "allow"
      // ^ skill reference files live inside the plugin install (read at runtime by skills)
      config.permission.external_directory["/tmp/qa-evidence/*"] = "allow"
      // ^ QA screenshots and recordings saved during web-qa / mobile-qa investigations

      // Register the plugin's MCP servers from its bundled .mcp.json — the single
      // source of truth shared with Claude Code (bundled) and Codex (manifest).
      // Translate the .mcp.json shape to OpenCode's { type: "local", command: [...] }.
      if (!config.mcp) config.mcp = {}
      try {
        const manifest = JSON.parse(readFileSync(path.resolve(pluginsDir, ".mcp.json"), "utf8"))
        for (const [name, server] of Object.entries(manifest.mcpServers || {})) {
          config.mcp[name] = {
            type: "local",
            command: [server.command, ...(server.args || [])],
          }
        }
      } catch {
        // .mcp.json missing/unreadable — skip; QA skills will report the missing MCP.
      }
    },

    "shell.env": async (_input, output) => {
      output.env.PLUGIN_ROOT = pluginsDir
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      const firstUser = output.messages.find((m) => m.role === "user")
      if (!firstUser) return
      if (!firstUser.parts) return
      if (firstUser.parts.some((p) => p.text?.includes("EXTREMELY_IMPORTANT")))
        return

      firstUser.parts.unshift({
        type: "text",
        text: getBootstrap(),
      })
    },
  }
}
