# Usage guide

See the [README](../README.md) for installation and a first run.

## Interactive questions

The normal command now pauses after transcription to ask for missing context:

```bash
python -m explain_video input.mp4
```

1. The first text-model call reads the transcript and any `--facts` you supplied,
   and proposes up to five practical questions a non-technical colleague might ask.
   It focuses on missing conditions, quantities, next steps, and exceptions, rather
   than questions already answered by the source material.
2. All questions are displayed, then you answer each in the terminal. Answers may
   span several lines; finish with an empty line. Press Enter immediately to skip
   a question. “I don't know” is also a valid answer, retained as uncertainty.
3. The second text-model call combines the transcript, supplied facts, and answered
   questions into the narration script. The normal voice/render stages follow.

This is two text-model calls, in addition to transcription and TTS; no iterative
question-generation loop is used. If the first call finds no useful questions,
rewriting proceeds immediately. Questions are suggestions, not facts: skipped
questions are excluded from the rewrite input, and the prompt forbids inventing
their answers. Facts already in the recording remain usable even if you skip.

`input.questions.json` records questions and answers, and is updated atomically
after each completed answer. Metadata records the model, counts, and artifact
hash. Ctrl-C or closed input stops before rewriting/TTS and preserves completed
answers plus the transcript. An unfinished multiline answer is not saved.
There is no automatic resume: retained answers can be copied into a facts file
for a new version using `--output-prefix`.

For unattended use, explicitly skip this step:

```bash
python -m explain_video input.mp4 --non-interactive --facts extra-facts.txt
```

Without a terminal, the CLI fails before paid calls unless `--non-interactive`
or `--script` is supplied. Questions/answers remain local artifacts and are sent
to OpenAI as part of the text calls. The question step uses speech text; optional
`--sync` separately analyzes sampled video frames after the script is ready.

## Experimental synchronization

The original workflow remains the default. Opt in with:

```bash
python -m explain_video input.mp4 --sync
```

This runs the same interactive questions and rewrite, using Whisper timestamped
transcription instead of the default transcription model. After the script is
ready, an additional GPT-4.1 mini call receives timestamped speech and at most 24
sampled screenshots (about one every four seconds on short videos). It divides
the script into a few meaningful sections and associates them with source-video
intervals. The model cannot change or reorder the script: validation requires
complete text coverage and chronological intervals covering the whole video.

Each section gets separate narration with the selected voice/style, then its own
video timing adjustment. Video speed is capped at 0.9–1.1×; excess speech holds
the section's final frame, while short speech leaves silence inside that section.
Narration pitch/speed is never altered. All source time is retained in order.
Output is H.264 at source resolution (even-dimension padding if needed), 30 fps,
with AAC encoded once after concatenating PCM scene audio. Holds or quiet gaps
over three seconds are reported by scene. Separate synthesis can introduce voice
variation; inspect timing and delivery before sharing.

For a fair comparison using an already approved script:

```bash
python -m explain_video input.mp4 --sync --script input.script.txt
```

`--script` skips questions and rewriting; it still transcribes the source for
alignment timestamps. It cannot be combined with `--facts`. Without `--sync`,
`--script` can also produce another whole-video voice rendition.

By default synced results use `input.synced.*`, preserving the ordinary output.
Use `--output-prefix another-version` for subsequent experiments. Extra artifacts:

- `input.synced.timestamps.json`: source-speech timestamps.
- `input.synced.sync-plan.json`: validated plan before synthesis, including sample
  times, script hash, and the planner's reported token usage.
- `input.synced.sync.json`: source-to-output interval map, narration durations,
  speed changes, holds and gaps.
- `input.synced.sync-assets/`: sampled screenshots, raw planner response, separate
  voice WAVs, and encoded scene parts. These remain available if a later stage fails.

The final `voice.wav` is the assembled narration timeline including inserted
silence; metadata's `narration_duration` is spoken-audio duration before padding.
There is no automatic paid retry or resume. A failed attempt keeps its completed
artifacts; use a new prefix to start over. These artifacts are ignored by Git.

Sync sends actual screen images to OpenAI, unlike the normal audio/text-only
workflow. Sampling may miss brief changes, and a model's plausible timing plan
is not proof of visual alignment. No screen content is treated as new factual
authority for rewriting the approved explanation.

## Add facts you forgot to say

Write extra context in a UTF-8 text file, then pass it with the video:

```bash
EXPLAIN_TTS_PROVIDER=openai python -m explain_video input.mp4 \
  --voice marin --facts extra-facts.txt --output-prefix input-v2
```

`--output-prefix` creates a separate version (`input-v2.explained.mp4`, etc.)
without replacing the previous result. Its parent directory must already exist.
It does not reuse previous API results: an ordinary CLI run processes all stages.

Facts can be plain sentences or bullets in Russian or English. Include the
actual approximate count and its conditions if those were missing from the video;
the program must not invent a threshold. For example, a facts file could say:

```text
Уточнение: речь идёт об ответах на отзывы, а не об отправке самих отзывов.
```

The rewrite receives the transcript and facts as separate sources, and is
instructed to integrate relevant facts naturally, retain approximate quantities
and qualifications, and use explicitly marked corrections over the original
speech. Unmarked contradictions should remain uncertain rather than silently
choosing a version. These are LLM instructions, not a deterministic fact checker;
review the saved script, especially numeric claims.

The normalized facts are saved as `input-v2.facts.txt`, with their SHA-256 in
metadata; the transcript remains a record of the spoken words only. Name your
input facts file differently from that output snapshot (such as `extra-facts.txt`).
Missing, empty, or non-UTF-8 facts files fail before any paid requests. Facts are
sent to the rewrite provider and may appear in the narration. Without `--facts`,
the interactive questions can collect missing context instead.

Outputs beside the input:

```text
input.explained.mp4
input.transcript.txt
input.script.txt
input.meta.json
input.voice.wav
```

The source is never overwritten. Existing output files, including symlinks, cause
an error before transcription. To rerun, move previous artifacts aside or give the
input a new name. Completed transcript/script/voice artifacts survive a later
stage failure. Temporary extracted source audio is removed on normal exit,
failure, or Ctrl-C. A forcibly killed process may leave a `.explain-video-*`
temporary directory. There is no automatic resume or paid retry in v0.

## Providers and voice

- Transcription: OpenAI `gpt-4o-mini-transcribe`, Russian language hint.
- Rewriting: OpenAI `gpt-4.1-mini`, with Russian instructions
  plus preservation of uncertainty, action order, names, numbers and negations.
- Default TTS: OpenAI `gpt-4o-mini-tts`, voice `marin`, with warm,
  friendly delivery.
- Optional TTS: `edge-tts`, voice `ru-RU-SvetlanaNeural`. This uses Microsoft's
  online service without a speech API key; it is not an offline engine.

These are small provider classes, not a plugin framework. Change model names in
`.env` if your account needs another supported model. Account access is not
established by installing this project. No local transcription/rewrite models
are bundled; an OpenAI API key is required even with Edge narration.

```bash
python -m explain_video input.mp4
```

The default provider and voice are:

```dotenv
EXPLAIN_TTS_PROVIDER=openai
EXPLAIN_VOICE=marin
```

With `gpt-4o-mini-tts`, delivery can be directed separately from the voice using
`EXPLAIN_TTS_INSTRUCTIONS` in `.env`. Leave it blank to use the default
friendly style, or supply your own direction. For example:

```dotenv
EXPLAIN_TTS_INSTRUCTIONS="Говори по-русски тепло, дружелюбно и чуть бодрее, с лёгкой улыбкой в голосе. Сохрани естественный тембр выбранного голоса. Без театральности и рекламного энтузиазма."
```

This changes delivery, not the rewritten text. The instructions used are recorded
in output metadata. Other TTS models and Edge do not use this setting.

Provider failures stop with an error; there is no silent
fallback to another service. Voice naturalness must be judged on the real sample.

API calls incur the provider's normal charges. Extracted audio is sent to OpenAI
for transcription, the transcript to OpenAI for rewriting, and the rewritten
script to the selected TTS provider. Screen frames are processed locally unless
`--sync` is enabled, which sends sampled screenshots to OpenAI for timing analysis.
`store=false` is used for the rewrite response; this is not a promise about all
provider retention. Credentials are excluded from metadata and Git. Text and
voice artifacts remain locally beside the video.

Provider contracts were checked against the official
[transcription](https://developers.openai.com/api/docs/guides/speech-to-text),
[text generation](https://developers.openai.com/api/docs/guides/text), and
[speech generation](https://developers.openai.com/api/docs/guides/text-to-speech)
documentation, and the [edge-tts project](https://github.com/rany2/edge-tts).
When sharing OpenAI-generated narration, disclose that the voice is synthetic
(for example in the accompanying message); the narration itself does not announce
that the explanation was rewritten.

## Timing and media decisions

This v0 matches overall duration. It cannot align individual sentences with
clicks; the rewrite prompt asks it to retain action order but cannot guarantee
that timing. Preview the MP4 before sending it.

- If `video_duration / narration_duration` is between 0.9 and 1.1 inclusive,
  change video speed to match. Narration is never sped up or pitch-shifted.
- If narration is longer outside that range, keep original video speed and hold
  its final frame until speech finishes.
- If narration is shorter outside that range, keep all footage at original speed
  and pad the narration with silence. No automatic tail trimming.
- Holds or quiet tails over three seconds are reported in the summary and metadata.

The output contains only the first video stream and the new narration. **All
original audio tracks are excluded.** Transcription uses the first input audio
track; a multi-track recording produces a diagnostic note. If your OBS microphone
is on a different track, export a recording with the intended track first.

The video is encoded as H.264 CRF 18, at original resolution (with at most one pixel
of padding to make dimensions even), and narration as AAC 192 kbps. MP4 faststart
helps playback after sharing. Re-encoding is needed for the timing filters; there
is no low-resolution conversion. This v0 targets ordinary SDR screen recordings.

Audio extraction is mono 16 kHz PCM WAV. The 25 MB transcription limit bounds v0
to roughly 13 minutes; oversized extracted audio fails before upload. OpenAI TTS
text is split into bounded chunks and concatenated locally. Very short/empty speech
and transcription mistakes still require human review; a nonempty transcript is
not proof of accuracy.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Tests exercise filename generation, no-clobber publication, configuration,
rewrite/transcription/TTS HTTP contracts, rejected/incomplete responses, and
duration decisions. Real ffmpeg smoke tests run all three timing branches and
measure audio frequencies to verify that the new audio replaced the source.
They also check missing audio, retained intermediates on failure, unchanged input
bytes, output duration, resolution, and stream count. Tests use synthetic content
and mocked paid APIs; they make no network calls.

Interactive tests verify the two-call request contracts, bounded question lists,
multiline answers, skipped/no questions, non-terminal preflight, and preservation
of completed answers when cancelled. Structured question output follows the
[OpenAI Structured Outputs contract](https://developers.openai.com/api/docs/guides/structured-outputs).


## Reviewing a result

Use a recording you have permission to process. Preview the output and read the
saved script: check names, numbers, negations, action order, narration quality,
and alignment with visible actions. Automated tests cannot judge explanation
quality. The tool has no GUI, subtitles, zooms, or highlights.
