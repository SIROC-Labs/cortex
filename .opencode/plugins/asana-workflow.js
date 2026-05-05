import path from "node:path"
import { fileURLToPath } from "node:url"

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

- **feature-dev@claude-plugins-official**: Not available. Implement feature
  development workflows inline in this session.
- **superpowers@claude-plugins-official**: Check if superpowers is installed
  via opencode.json plugins. If present, invoke its skills normally via the
  native skill tool. If absent, implement the equivalent workflow inline.

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

const BOOTSTRAP = [
  TOOL_MAPPING,
  EXTERNAL_DEPS,
  CLAUDE_MD_MAPPING,
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
