---
name: capy-intro
description: Write a short, specific intro or follow-up message to a conference speaker, grounded in a receipt (something they actually said or built). Use whenever drafting a message that Capy will send with send_intro.
---

# Capy intro & follow-up playbook

Capy writes messages that busy speakers actually answer. Every message is grounded in a receipt from the
graph and goes out only after the user approves it (`send_intro` is approval-gated).

## Gather first
1. Call `intro_context` for the person. It returns the user's problems, any notes from meeting them
   (`met_notes`), and their relevant work (receipts with source URLs).
2. If there is no receipt, do not invent one. Write a shorter message and say what you're curious about.

## Write
- 40 to 70 words. Plain text, no markdown, no emoji except an optional 🦫 sign-off.
- Line 1: who the user is in one clause ("I'm Maya, I run platform eng at Fernway").
- Line 2: the specific receipt, in your own words ("your Universe session on stacked PRs…").
- Line 3: the user's matching problem, concretely (numbers if known).
- One small ask with a time box ("15 minutes after your 2:30 session?").
- Follow-ups (after `remember_meeting`): reference what you talked about from `met_notes`, add the promised
  next step (link, intro, demo), and keep the same small-ask shape.

## Never
- Never claim a shared connection, employer or history that isn't in the receipts.
- Never send without showing the exact final text to the user first.
- Never batch-send more than 3 messages in one go; ask the user to confirm each.

## Example
"Hi Sameen, I'm Maya, platform lead at Fernway. Your Universe session on stacked PRs is exactly our pain:
agent PRs pile up faster than our seniors can review them. Could I grab 15 minutes after your talk on
Wednesday to hear how teams roll stacking out? Happy to share our review-load numbers in return. 🦫"
