## waker supervisor

When the user says "use waker", "watch this", or "finish it":

1. If a run is active: every time the user sends a message, run
   `waker status --format md --repo .` and insert the full table before
   answering.
2. New run:
   - `waker plan --prompt "<verbatim>" --out .waker/tasks.yaml --repo .`
   - Print the file + lint warnings, then ask `OK to run?`
   - `waker start --detach --repo . --tasks .waker/tasks.yaml --test "<test command>" --adapter generic --agent "<agent command>"`
   - After starting, always say: "Running in the background. Ask me for
     progress in chat, or run `waker watch --repo .` for the live view."

3. Do not declare a task done yourself. Only `waker status` / `waker report`
   decide.
4. Do not edit `tasks.yaml` or test files after starting.
