import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const devToolkitDir = path.resolve(__dirname, "../../plugins/dev-toolkit")
const devToolkitSkillsDir = path.resolve(devToolkitDir, "skills")
const productDir = path.resolve(__dirname, "../../plugins/product")
const productSkillsDir = path.resolve(productDir, "skills")

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

const CLAUDE_MD_MAPPING = `
## Project Config File

When a skill instructs you to read CLAUDE.md, also check for AGENTS.md and
opencode.json. If AGENTS.md exists, prefer it. CLAUDE.md may contain
Claude Code-specific configuration that does not apply.
`

const SKILL_PATHS = `
## Skill File Resolution

The dev-toolkit plugin has its skills at: ${devToolkitSkillsDir}

The product plugin has its skills at: ${productSkillsDir}

When a skill instructs you to read a reference file, resolve paths as follows:

- Paths starting with \`plugins/dev-toolkit/\` map to \`${devToolkitDir}/\`.
- Paths starting with \`plugins/product/\` map to \`${productDir}/\`.
- Relative paths like \`references/xxx.md\` are relative to the current
  skill's own directory (e.g. \`.../skills/create-spec/references/xxx.md\`).

When reading a skill's reference files, use the absolute filesystem path
shown above — do NOT guess paths relative to your current working directory.
`

const BOOTSTRAP = [TOOL_MAPPING, CLAUDE_MD_MAPPING, SKILL_PATHS].join("\n")

let _bootstrapCache = null

function getBootstrap() {
  if (_bootstrapCache) return _bootstrapCache
  _bootstrapCache = `<EXTREMELY_IMPORTANT>
You are running the SIROC Cortex plugins (dev-toolkit, product) under OpenCode.

Use the native skill tool to list their skills and load them as needed.

${BOOTSTRAP}
</EXTREMELY_IMPORTANT>`
  return _bootstrapCache
}

export const CortexPlugin = async () => {
  return {
    config: async (config) => {
      config.skills ??= {}
      config.skills.paths ??= []
      config.skills.paths.push(devToolkitSkillsDir)
      config.skills.paths.push(productSkillsDir)

      config.permission ??= {}
      config.permission.external_directory ??= {}
      config.permission.external_directory[`${devToolkitDir}/*`] = "allow"
      config.permission.external_directory[`${productDir}/*`] = "allow"
      // ^ skill reference files live inside the plugin install (read at runtime by skills)
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
