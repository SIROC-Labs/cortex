# Reporting

## Confidence Levels

Use exactly one of these for each finding:

| Level | Definition | Required Evidence |
|---|---|---|
| **Confirmed** | Reproduced with evidence | Screenshot, recording, log output, or trace showing the issue |
| **Likely** | Strong reasoning, not fully reproduced | Partial evidence + explanation of what couldn't be verified and why |
| **Suspicion** | Noticed during investigation, unverified | Description of what was observed + what would need to happen to verify |

## Report Structure

Every report follows this structure:

### 1. Answer
Direct answer to the operator's question. Lead with this — no preamble.

### 2. Root Cause (if applicable)
What's causing the behavior. Include confidence level. If source code is available, include file:line references.

### 3. Reproduction Steps
Numbered steps anyone can follow:

```
1. Open the SUT
2. Navigate to [screen/page/view]
3. Interact with [element]
4. **Expected:** [what should happen]
5. **Actual:** [what happens instead]
```

Be specific: exact targets, exact element descriptions, exact inputs. Someone with no context should be able to follow these steps.

### 4. Evidence
Include all captured evidence:

- **Screenshots** — at key moments (before, during, after the issue)
- **Recordings** — for transitions, animations, multi-step flows
- **Log output** — exact error messages with stack traces
- **Traces** — failed requests, unexpected responses, timing issues

### 5. Source Context (if source code available)
File and line references explaining the code path that produces the behavior.

### 6. Recommendation
Suggested fix or next steps. Be specific — name the file, the function, the change.

## Output

The report IS the primary artifact. The skill takes a question as input and produces the report as output. When invoked from `start-task` with a task GID in context, the report is also posted to the task manager (see `process.md` Step 6). In standalone invocations, the operator decides what to do with the report.
