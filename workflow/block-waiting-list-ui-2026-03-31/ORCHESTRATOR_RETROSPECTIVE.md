# Orchestrator Retrospective

## Block
- block-waiting-list-ui-2026-03-31

## What Worked
- mechanical task routing with immutable archived artifacts made recovery easier
- minimal Gemini acceptance prompts were much more reliable than heavy compiled PM packets for final acceptance

## What Slowed The Team Down
- external CLI workers sometimes delayed final JSON long after useful work was already done
- per-task PM acceptance created extra orchestration latency without clear quality gain

## Communication Issues
- a final-style user message was sent once before the block was actually closed

## Tooling Issues
- worker runners lacked built-in idle detection and artifact probing at the start of the session

## Suggested Workflow Changes
- keep PM focused on block acceptance while executor owns task acceptance
- use generated prompt files and workflow health summaries by default
