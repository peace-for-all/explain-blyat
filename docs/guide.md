# A short guided recording

Run `./run --guide` (or `explain-video --guide` after a pip install).
It creates a standalone `recording-guide.html` in your current directory and
opens it in your browser. If opening fails, use the printed file link. Existing
files are preserved; subsequent guides get numbered names.

Write short answers to four questions, in any language:

1. What do you want to do?
2. What’s getting in the way?
3. How do you do it?
4. How do you know it worked?

Aim for 1–2 minutes, spending most of that time showing the steps. Click
**Use recording view** to turn your answers into cues. The whole vertical list
stays visible; clicking any question highlights it. Nothing advances automatically.
**Edit answers** returns to the text fields without losing your answers.

Keep the browser beside your demo and outside the area being captured. Use
Kooha's area selection on Linux, or Shift–Command–5 → Record Selected Portion
on macOS. Enable your microphone. Start and stop the recorder separately;
the guide's optional timer does not control recording. Starting the timer again
resets it to zero. The guide does not enforce a time limit.

Use **Save answers** to download `recording-plan.json`; **Load answers** restores
it later. Answers live only in the tab until downloaded, so save before closing.
The page has no network requests, API calls, or browser storage. Keep downloaded
plans private as needed; default plan and generated guide filenames are Git-ignored.

After stopping the recorder, run:

```bash
./run "path/to/recording.mov"
```

This starts the existing clarification and voice-replacement workflow. Planning
answers are not automatically supplied as facts: verify against what you actually
recorded. This first guide uses your own answers; automatic LLM tailoring, joke
suggestions, and integrated recording are not included.
