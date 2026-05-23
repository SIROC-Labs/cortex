# Skill Reference Graph

> Auto-generated — do not edit manually.
> Last updated: 2026-05-23 10:41

```mermaid
graph TD
    create-pr --> git-check
    create-pr --> log-task
    create-pr --> pre-ship-check
    create-pr --> ship-it
    create-pr --> start-task
    create-pr --> work-summary
    fix-bug --> start-task
    git-check --> create-pr
    git-check --> pre-ship-check
    log-task --> asana-api
    log-task --> create-pr
    log-task --> ship-it
    log-task --> start-task
    pre-ship-check --> asana-api
    pre-ship-check --> git-check
    pre-ship-check --> ship-it
    pre-ship-check --> start-task
    ship-it --> asana-api
    ship-it --> create-pr
    ship-it --> fix-bug
    ship-it --> git-check
    ship-it --> log-task
    ship-it --> pre-ship-check
    ship-it --> start-task
    ship-it --> work-summary
    start-task --> asana-api
    start-task --> fix-bug
    start-task --> mobile-qa
    start-task --> pre-ship-check
    start-task --> ship-it
    start-task --> web-qa
    work-summary --> asana-api
    work-summary --> create-pr
    work-summary --> ship-it
```
