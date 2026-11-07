# 45-second demo script

Record at 1080p, 24–30 fps. Terminal font 16px. Dark theme. No voice-over
needed — captions only.

| Time | Shot | Caption |
|---|---|---|
| 0:00–0:05 | Title card + slogan | "Never let your AI coding agent sleep on the job again." |
| 0:05–0:10 | Terminal: `waker plan --prompt "Phase 1: auth, scope: src/auth/**, verify: pytest tests/auth -q"` | "Turn a prompt into a mechanical contract — 0 tokens." |
| 0:10–0:16 | Output: `tasks.yaml` + lint warnings | "Missing `verify`? It refuses to run." |
| 0:16–0:24 | Terminal: `waker start --detach ...` then `waker watch` | "It runs in the background, even if you close the chat." |
| 0:24–0:32 | Split screen: fake lazy agent finishes 1/2, status turns red | "Agent stopped at 1/2. Waker caught it." |
| 0:32–0:38 | Status: kick #1 → 2/2, test PASS | "It woke the agent with the exact missing task." |
| 0:38–0:42 | `waker report` + `waker dashboard --open` | "Every claim backed by a file and a passing command." |
| 0:42–0:45 | GitHub URL + slogan | "waker-ai. Ship while you sleep." |

## Recording commands

```powershell
# terminal 1 - the supervisor
waker start --detach --repo . --tasks .waker/tasks.yaml `
  --adapter opencode --model opencode-go/deepseek-v4.1-flash `
  --test "pytest tests/ -q" --max-kicks 5 --max-cost 0.50

# terminal 2 - the live board
waker watch --repo .

# terminal 3 - the report / dashboard
waker report --repo .
waker dashboard --repo . --open
```

For a deterministic demo (no model cost), use the fake agent:

```powershell
waker run --repo . --tasks .waker/tasks.yaml `
  --test "pytest tests/ -q" --adapter generic `
  --agent "python tests/fake_agent.py --mode lazy --repo ."
```

## Shot list tips

- Show the **red → green** transition: it is the product.
- Keep the cursor visible when typing the command.
- Cut the model thinking time; keep the timer in the status bar.
- End on the report: task, evidence, test exit code, cost.
