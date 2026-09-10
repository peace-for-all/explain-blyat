import json
import hashlib
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from . import media
from .providers import QuestionProvider, RewriteProvider, TranscriptionProvider, TTSProvider, nonempty, validate_questions
from .sync import SyncEngine, render_synced


def output_paths(source: Path, prefix: Path | None = None, *, include_facts: bool = False,
                 include_questions: bool = False, include_sync: bool = False) -> dict[str, Path]:
    base = prefix if prefix is not None else source.with_name(source.stem)
    paths = {key: base.with_name(base.name + suffix) for key, suffix in {
        "video": ".explained.mp4", "transcript": ".transcript.txt", "script": ".script.txt",
        "meta": ".meta.json", "voice": ".voice.wav"}.items()}
    if include_facts:
        paths["facts"] = base.with_name(base.name + ".facts.txt")
    if include_questions:
        paths["questions"] = base.with_name(base.name + ".questions.json")
    if include_sync:
        for key, suffix in {"sync_plan": ".sync-plan.json", "sync": ".sync.json",
                            "timestamps": ".timestamps.json", "sync_assets": ".sync-assets"}.items():
            paths[key] = base.with_name(base.name + suffix)
    return paths


def publish(source: Path, target: Path) -> None:
    # Atomic no-clobber publication on the same filesystem (including symlinks).
    os.link(source, target)


def run_pipeline(source: Path, transcription: TranscriptionProvider, rewrite: RewriteProvider,
                 tts: TTSProvider, voice: str, progress: Callable[[str], None] = print,
                 *, facts: str | None = None, output_prefix: Path | None = None,
                 question_provider: QuestionProvider | None = None,
                 answer_question: Callable[[str, int, int], str | None] | None = None,
                 sync_engine: SyncEngine | None = None, narration_script: str | None = None) -> dict:
    source = source.absolute()
    if not source.is_file():
        raise ValueError(f"Input file not found: {source}")
    media.check_tools()
    if facts is not None:
        facts = nonempty(facts, "Facts")
    if narration_script is not None:
        narration_script = nonempty(narration_script, "Supplied script")
        if facts is not None or question_provider is not None:
            raise ValueError("A supplied script cannot be combined with facts or interactive rewriting")
    if question_provider is not None and answer_question is None:
        raise ValueError("Interactive mode needs an answer callback")
    paths = output_paths(source, output_prefix, include_facts=facts is not None,
                         include_questions=question_provider is not None, include_sync=sync_engine is not None)
    paths = {key: path.absolute() for key, path in paths.items()}
    if not paths["video"].parent.is_dir():
        raise ValueError("Output directory does not exist; create it before running")
    for path in paths.values():
        if os.path.lexists(path):
            raise ValueError(f"Output already exists: {path.name}; move existing artifacts or rename the input")
    info = media.probe(source)
    video_duration = media.duration(info, "video")
    media.duration(info, "audio")
    warnings = []
    total = 6 if question_provider is not None else 5
    answers = []
    interview = None
    sync_result = None
    if sum(s["codec_type"] == "audio" for s in info["streams"]) > 1:
        warnings.append("Multiple audio tracks: transcribed the first audio track only.")
    with tempfile.TemporaryDirectory(prefix=".explain-video-", dir=paths["video"].parent) as directory:
        work = Path(directory)
        # Probe the destination before any paid call. FAT/exFAT and some network
        # mounts cannot provide the hard links used for no-clobber publication.
        probe_source = work / "link-check"
        probe_target = work / "link-check-copy"
        probe_source.touch()
        try:
            os.link(probe_source, probe_target)
        except OSError as error:
            raise ValueError(
                "Output directory must support hard links; use --output-prefix "
                "in a writable local Linux filesystem directory"
            ) from error
        probe_target.unlink()
        probe_source.unlink()
        if sync_engine is not None:
            paths["sync_assets"].mkdir()
        if facts is not None:
            (work / "facts.txt").write_text(facts + "\n", encoding="utf-8")
            publish(work / "facts.txt", paths["facts"])
        progress(f"1/{total} Extracting audio…")
        audio = work / "original.wav"
        media.extract_audio(source, audio)
        progress(f"2/{total} Transcribing Russian speech…")
        transcript = nonempty(transcription.transcribe(audio), "Transcription")
        (work / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")
        publish(work / "transcript.txt", paths["transcript"])
        if sync_engine is not None:
            (work / "timestamps.json").write_text(json.dumps(sync_engine.transcription.segments, ensure_ascii=False, indent=2), encoding="utf-8")
            publish(work / "timestamps.json", paths["timestamps"])
        if question_provider is not None:
            progress(f"3/{total} Finding useful listener questions…")
            questions = validate_questions(question_provider.questions(transcript, facts=facts))
            interview = {"model": question_provider.model, "status": "collecting", "items": [
                {"question": q, "answer": None, "status": "pending"} for q in questions]}
            def save_interview(first=False):
                # Write a new inode each time: published journal remains intact until replace.
                temporary = work / "questions-next.json"
                temporary.write_text(json.dumps(interview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                if first:
                    publish(temporary, paths["questions"])
                    temporary.unlink()
                else:
                    os.replace(temporary, paths["questions"])
            save_interview(first=True)
            if questions:
                progress("\nВозможные вопросы коллеги:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)))
            else:
                progress("Существенных вопросов нет — продолжаем.")
            try:
                for index, item in enumerate(interview["items"], 1):
                    answer = answer_question(item["question"], index, len(questions))
                    if answer is not None and not isinstance(answer, str):
                        raise ValueError("Answer must be text or skipped")
                    answer = answer.strip() if answer else None
                    item.update(answer=answer or None, status="answered" if answer else "skipped")
                    if answer:
                        answers.append({"question": item["question"], "answer": answer})
                    save_interview()
            except (KeyboardInterrupt, EOFError, RuntimeError, ValueError):
                interview["status"] = "cancelled"
                save_interview()
                raise
            interview["status"] = "completed"
            save_interview()
        progress("Using the supplied narration script…" if narration_script is not None else f"{total-2}/{total} Rewriting the explanation…")
        context = {}
        if facts is not None:
            context["facts"] = facts
        if answers:
            context["answers"] = answers
        rewritten = narration_script if narration_script is not None else rewrite.rewrite(transcript, **context)
        script = nonempty(rewritten, "Rewrite")
        (work / "script.txt").write_text(script + "\n", encoding="utf-8")
        publish(work / "script.txt", paths["script"])
        if sync_engine is not None:
            progress("Planning scene timing from speech timestamps and sampled screen images…")
            plan = sync_engine.plan(source, script, paths["sync_assets"], video_duration)
            (work / "sync-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            publish(work / "sync-plan.json", paths["sync_plan"])
            sync_result = render_synced(source, script, plan, tts, voice, paths["sync_assets"], work, progress)
            (work / "sync.json").write_text(json.dumps(sync_result, ensure_ascii=False, indent=2), encoding="utf-8")
            publish(work / "sync.json", paths["sync"])
            narration_duration = sync_result["narration_duration"]
            warnings.extend(sync_result["warnings"])
            timing = None
            adjustment = f"Scene-aligned narration across {len(sync_result['scenes'])} sections"
        else:
            progress(f"{total-1}/{total} Generating narration…")
            tts.synthesize(script, work / "voice.wav", voice)
            narration_duration = media.duration(media.probe(work / "voice.wav"), "audio")
            publish(work / "voice.wav", paths["voice"])
            timing = media.choose_timing(video_duration, narration_duration)
            if timing.quiet_seconds > 3:
                warnings.append(f"Quiet tail is {timing.quiet_seconds:.1f}s; all screen actions were preserved.")
            if timing.freeze_seconds > 3:
                warnings.append(f"Final-frame hold is {timing.freeze_seconds:.1f}s; review narration alignment.")
            progress(f"{total}/{total} Rendering MP4…")
            media.render(source, work / "voice.wav", work / "output.mp4", timing)
            adjustment = timing.description
        if sync_engine is not None:
            publish(work / "voice.wav", paths["voice"])
        output_info = media.probe(work / "output.mp4")
        metadata = {
            "input_duration": video_duration, "narration_duration": narration_duration,
            "output_duration": media.duration(output_info, "video"),
            "transcription_provider": transcription.name,
            "transcription_model": getattr(transcription, "model", None),
            "rewrite_model": rewrite.model if narration_script is None else "supplied-script", "tts_provider": tts.name,
            "tts_model": getattr(tts, "model", None), "voice": voice,
            "tts_instructions": getattr(tts, "instructions", None) if getattr(tts, "model", "").startswith("gpt-4o-mini-tts") else None,
            "video_adjustment": adjustment, "timing": asdict(timing) if timing is not None else None,
            "warnings": warnings, "synchronization": "timestamp and screenshot scene plan" if sync_result is not None else "overall duration only; no scene alignment",
            "sync_artifact": paths["sync"].name if sync_result is not None else None,
            "narration_is_synthetic": True,
            "clarification": None if interview is None else {
                "model": interview["model"], "artifact": paths["questions"].name,
                "question_count": len(interview["items"]), "answered_count": len(answers),
                "sha256": hashlib.sha256(paths["questions"].read_bytes()).hexdigest(),
            },
            "auxiliary_facts": None if facts is None else {
                "artifact": paths["facts"].name,
                "sha256": hashlib.sha256((facts + "\n").encode("utf-8")).hexdigest(),
            },
        }
        (work / "meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        publish(work / "meta.json", paths["meta"])
        publish(work / "output.mp4", paths["video"])
    return metadata
