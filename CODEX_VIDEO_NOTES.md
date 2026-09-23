# Codex crash course — easy-to-follow notes

**Video:** [OpenAI Codex Crash Course – Build & Deploy Apps with Autonomous AI](https://www.youtube.com/watch?v=o3CX_Y59_74)  
**Creator:** freeCodeCamp.org, course by Skyrocketing Tech  
**Length:** 41 minutes, 18 seconds  
**Notes prepared:** 15 September 2026

These notes summarize the full English auto-generated transcript and the video’s chapter list, with a visual spot-check. Caption errors have been normalized. The final section applies the lessons to Zuvi; those examples are our project guidance, not claims made in the video.

## The main lesson

Codex can read a codebase, change files, run commands, test results, and work across connected tools. Getting a useful result depends on giving it enough context, a clear outcome, and a way to check its work.

The presenter’s workflow is:

**Explain the idea → clarify it in Plan mode → review the plan → set a Goal → build → test → revise → publish when ready.**

The game demonstration includes revisions after the first build. The presenter also says this is an introduction to the tools, rather than a complete production engineering workflow. [Opening](https://www.youtube.com/watch?v=o3CX_Y59_74&t=0s) · [Conclusion](https://www.youtube.com/watch?v=o3CX_Y59_74&t=2370s)

## 1. Get started and understand the controls

| Start | Topic | What to remember |
| --- | --- | --- |
| [01:17](https://www.youtube.com/watch?v=o3CX_Y59_74&t=77s) | Installation | Download the app from OpenAI, choose your operating system, install, and sign in. |
| [02:08](https://www.youtube.com/watch?v=o3CX_Y59_74&t=128s) | Plans and usage | Choose based on your actual usage. The presenter initially uses an expensive plan, then later explains that a cheaper plan suited his needs. |
| [03:27](https://www.youtube.com/watch?v=o3CX_Y59_74&t=207s) | Sidebar | Find conversations, projects, search, and scheduled work. |
| [05:08](https://www.youtube.com/watch?v=o3CX_Y59_74&t=308s) | Projects and chats | A project organizes related work around a folder. Chats are individual conversations. Use a project for ongoing app development. |
| [09:21](https://www.youtube.com/watch?v=o3CX_Y59_74&t=561s) | Interface changes | The course mixes recordings from different app versions. The presenter distinguishes general chat, practical Work tasks, and software work in Codex. |
| [14:02](https://www.youtube.com/watch?v=o3CX_Y59_74&t=842s) | Input and model controls | You can dictate prompts and choose a model, reasoning effort, and speed setting. These are separate choices. |

The presenter uses medium or higher reasoning depending on the task, rather than always selecting the maximum. He also describes faster processing as using his allowance more quickly.

**Do not treat the video’s prices, model rankings, reset explanation, or credit estimates as a current buying guide.** They describe his account and recordings at that time, and his plan changes during the video. This note does not recommend a subscription.

## 2. Give Codex useful context

At [17:06](https://www.youtube.com/watch?v=o3CX_Y59_74&t=1026s), the presenter shows permission settings and the attachment/context menu. Files, folders, connected apps, and relevant conversations help explain what the work involves.

At [07:09](https://www.youtube.com/watch?v=o3CX_Y59_74&t=429s), he explains why he stores durable project information in Notion: a long conversation should not be the only place where important decisions exist. Codex can retrieve that information through a connected tool when needed.

**Practical takeaway:** Keep requirements and decisions in a maintained document, and point Codex to the specific information needed for the task.

A useful request includes:

- The result you want.
- The files or project it belongs to.
- The rules it must follow.
- An example of correct behavior.
- The checks that prove the result works.

## 3. Plugins, skills, and schedules do different jobs

| Feature | Plain meaning | Example from the course |
| --- | --- | --- |
| Plugin | Adds connected tools or packaged capabilities. | Accessing Supabase or Notion; showing how Gmail connection begins. |
| Skill | Reuses instructions and resources for a particular kind of work. | Reusing an editorial design style for a new creator roadmap. |
| Scheduled task | Runs specified work at a chosen time or interval. | A one-time reminder about a minute later; a proposed monthly team report. |

**Plugin walkthrough — [07:09](https://www.youtube.com/watch?v=o3CX_Y59_74&t=429s):** Find the plugin, install it, connect the relevant account, then select or mention it in a request. The presenter stops before completing Gmail connection; it is a connection walkthrough, not a demonstrated email send.

**Reusable skill walkthrough — [19:13–26:04](https://www.youtube.com/watch?v=o3CX_Y59_74&t=1153s):** Capture a successful design approach in a Markdown instruction file. Invoke that skill with new content to reproduce the approach. The presenter’s new roadmap keeps the earlier design style. He then proposes combining the skill with a scheduled report.

**Scheduled task walkthrough — [03:27–07:09](https://www.youtube.com/watch?v=o3CX_Y59_74&t=207s):** Describe what should run and when. Check the created schedule and its result. The demonstration’s one-time reminder runs and is then removed so it will not repeat.

Current official guidance defines a skill as a package of task instructions and supporting resources. A plugin can bundle skills and connected tools. Codex supports `$` mentions for skills. [OpenAI: Skills & Plugins](https://learn.chatgpt.com/docs/skills-and-plugins)

## 4. Learn the few controls that matter most

The video introduces `/` commands, `@` mentions, and `$` skills. The pet is an optional visual indicator of activity; it is not required for the development workflow.

| Control | Use |
| --- | --- |
| `/plan` | Clarify a task and develop an implementation plan. |
| `/goal` | Set an outcome for Codex to keep working toward. |
| `$` | Find and select an enabled skill. |
| `@` or the attachment menu | Add supported context or connected resources. |
| `/model` | Select a model. |
| `/reasoning` | Select reasoning effort. |
| `/fast` | Toggle faster processing when available. |
| `/review` | Start a code review. |

**Naming correction:** The video chapter says “Go Mode,” and captions sometimes show `/go`. The current documented command is **`/goal`**. Type `/` and use the command offered by your app; available commands depend on the environment and access. [OpenAI: Slash commands](https://learn.chatgpt.com/docs/reference/slash-commands)

## 5. Plan first when the outcome is unclear

At [26:04](https://www.youtube.com/watch?v=o3CX_Y59_74&t=1564s), the presenter explains the distinction:

| Plan mode | Goal mode |
| --- | --- |
| Helps decide what should be built and how. | Works toward an already defined result. |
| Clarifies requirements through questions. | Implements, checks, and iterates toward completion. |
| Produces a plan to review and refine. | Uses the outcome as the target for the work. |

His sequence is to describe an idea in Plan mode, answer the questions, review the resulting plan, and then use it to start a goal. In the recorded interface, selecting one mode replaces the other.

**A strong goal describes the outcome, constraints, and verification.** For example, “Make this form reject invalid quantities and demonstrate that valid submissions still work” gives a clearer finish line than “Improve the form.” Official guidance also recommends `/plan` before `/goal` when the outcome needs clarification. Goal mode retains existing permissions and may pause for required input; it does not provide unlimited access. [OpenAI: Long-running work](https://learn.chatgpt.com/docs/long-running-work)

## 6. Follow the game example from idea to revision

The practical example is a Flappy Bird-style game where the player’s voice keeps the bird airborne against gravity.

1. **Describe the idea — [30:25](https://www.youtube.com/watch?v=o3CX_Y59_74&t=1825s).** The presenter asks for voice control instead of the usual tapping.
2. **Answer planning questions.** Codex asks several rounds of questions and produces an implementation plan.
3. **Start the goal.** The presenter passes the plan into Goal mode to demonstrate sustained implementation. Codex edits files and generates artwork.
4. **Test the first build — [34:32](https://www.youtube.com/watch?v=o3CX_Y59_74&t=2072s).** The first version has issues. He tries it himself before requesting revisions.
5. **Give feedback and test again.** He sends a follow-up request, opens the updated hosted game, enables the microphone, and tests the voice-level controls and scoring.
6. **Publish and preserve the source — [38:20](https://www.youtube.com/watch?v=o3CX_Y59_74&t=2300s).** He shows the GitHub repository, its setup README, and a prompt intended to guide conversion to an Expo mobile app.

The course also introduces Sites earlier, at [12:07](https://www.youtube.com/watch?v=o3CX_Y59_74&t=727s), using a creator-roadmap website and its dashboard. At the end, the presenter changes the game’s visibility from private to public.

**What was actually demonstrated:** a web game, feedback-driven revisions, hosting, and a source repository. The Expo material is a proposed next step supplied as a prompt. The video does not demonstrate a completed iOS/Android release or establish store acceptance or revenue.

The accessible video description did not expose the promised game/repository links when these notes were prepared, so no guessed URLs are included here.

## 7. Apply the lessons to Zuvi

This section is an adaptation based on this project’s [AGENTS.md](AGENTS.md) and [README.md](README.md), not a summary of the presenter’s application.

**Keep project context nearby.** Start work in `Zuvi-Web-Postgres`. Use AGENTS.md for business and permission rules, and README.md for setup and deployment contracts. Save new decisions in project documents so later work can find them.

**Work on one clearly defined behavior at a time.** Examples include a product approval issue, an inventory validation bug, or a customer address problem. Give the expected result and affected user role.

**Include the rules in the finish line.** A change is only useful if it preserves store/customer isolation, Django permissions, backend pricing, audited inventory movements, and COD order rules where applicable.

**Keep the existing architecture.** The course’s Supabase, Sites, and Expo examples do not require replacing Zuvi’s Django/PostgreSQL setup. This repository documents Railway deployment and private S3 media storage with separate UAT and production environments.

**Review evidence before release.** Ask for the behavior change, relevant test results, and remaining limitations. Publishing the demo game is not a deployment procedure for Zuvi; follow this project’s documented environment and release process.

### Copy-ready example: understand a problem

```text
Read AGENTS.md and README.md, then inspect the inventory adjustment flow.
Explain how it currently works in plain language. Identify where quantities,
store access, and audit history are enforced. Do not change files yet.
```

### Copy-ready example: plan a fix

```text
/plan
Investigate why [describe the observed problem] happens in Zuvi.
Expected behavior: [describe what should happen instead].
Follow AGENTS.md and the existing service layer. Inspect the current code
before proposing changes. Give me a focused plan with the affected files,
any decisions needed, and the checks that will prove the fix works.
```

### Copy-ready example: carry out a reviewed plan

```text
/goal
Implement the reviewed plan for [specific issue] in Zuvi.
Preserve the applicable permissions, store/customer isolation, and audit rules
in AGENTS.md. Follow README.md for isolated local validation. Fix failures
introduced by the change and report what changed, the checks run, and any
remaining limitations. Finish with a local change ready for review.
```

### A simple checklist for each task

- [ ] The desired behavior is clear.
- [ ] The relevant project rules and files have been read.
- [ ] Important uncertainties have been resolved.
- [ ] The implementation addresses the requested behavior.
- [ ] Appropriate checks demonstrate that it works.
- [ ] The result and remaining limitations are explained.

**Best takeaway for Zuvi:** use Codex in a repeatable cycle of clear requirements, focused implementation, meaningful verification, and review. Reusable skills and schedules become useful once that underlying process is reliable.
