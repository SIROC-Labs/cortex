The `{{stage}}` stage of the quality gate is failing on this branch after an
implementation you are picking up mid-flight. Fix it.

## Task being implemented

```json
{{task}}
```

## Failing command

```
{{command}}
```

## Output

```
{{output}}
```

## What to do

1. Diagnose the actual cause. Read the failing file and the code it exercises.
2. Fix the underlying problem.
3. Do not commit or push — the runner handles that.

Do not weaken the check to make it pass: deleting a test, loosening an assertion,
adding an ignore/suppress directive, or lowering a threshold is not a fix. If the check
itself is genuinely wrong, say so plainly and leave it failing rather than disabling it.

If the failure is unrelated to the task's changes (a pre-existing break, a flaky test,
a missing dependency in the environment), say so and fix it only if the fix is obvious
and contained.
