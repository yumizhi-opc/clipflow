"""ClipFlow CLI — entry point for all pipelines."""

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

STAGES = ["transcribe", "analyze", "plan", "cut", "compose", "render", "export"]


@click.group()
@click.version_option(version="1.0.0", prog_name="clipflow")
def main():
    """ClipFlow — Agent-native CLI video editor.

    Turn raw recordings into polished videos via commands that AI agents can chain.
    """
    pass


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--lang", type=click.Choice(["en", "zh", "zh-en"]), default="en",
              help="Language(s) spoken in the recording")
@click.option("--style", type=click.Choice(["tutorial", "bip", "lecture"]), default="tutorial",
              help="Cut style: tutorial (tight), bip (keeps personality), lecture (minimal)")
@click.option("--brief", type=str, default=None,
              help="Topic description to improve chapter naming")
@click.option("--broll", type=click.Path(exists=True, path_type=Path), default=None,
              help="Folder of B-roll images/clips for insertion")
@click.option("--brand", type=click.Path(exists=True, path_type=Path), default=None,
              help="Brand config YAML (logo, colors, font)")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output directory (default: ./clipflow_out/)")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would happen without executing")
def tutorial(file: Path, lang: str, style: str, brief: str | None,
             broll: Path | None, brand: Path | None, output: Path | None,
             dry_run: bool):
    """Run the tutorial auto-cut pipeline on a recording.

    \b
    Examples:
      clipflow tutorial recording.mp4
      clipflow tutorial recording.mp4 --lang zh-en --style bip
      clipflow tutorial recording.mp4 --lang zh-en --brief "Next.js + Printful setup"
    """
    from clipflow.pipeline.tutorial import TutorialPipeline
    from clipflow.project import ProjectSpec

    output = output or Path("./clipflow_out")
    output.mkdir(parents=True, exist_ok=True)

    spec = ProjectSpec.from_tutorial_args(
        file=file, lang=lang, style=style, brief=brief,
        broll=broll, brand=brand, output_dir=output,
    )

    if dry_run:
        console.print(Panel(
            spec.describe(),
            title="[bold]Dry run — tutorial pipeline[/bold]",
            border_style="blue",
        ))
        return

    pipeline = TutorialPipeline(spec, console=console)
    pipeline.run()


# ---------------------------------------------------------------------------
# Standalone stage runners
# ---------------------------------------------------------------------------

@main.group()
def stage():
    """Run individual pipeline stages.

    \b
    Use these to run one stage at a time, inspect results between stages,
    and re-run stages after making adjustments. Designed for AI agent workflows.

    \b
    Typical agent workflow:
      clipflow stage transcribe recording.mp4 -o out/
      # inspect out/transcript.json, fix errors
      clipflow stage analyze out/
      # review out/structure.json, adjust chapters
      clipflow stage plan out/
      # inspect out/edl.json, override cuts
      clipflow stage cut out/
      clipflow stage compose out/
      clipflow stage render out/
      clipflow stage export out/
    """
    pass


@stage.command("transcribe")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--lang", type=click.Choice(["en", "zh", "zh-en"]), default="en")
@click.option("--style", type=click.Choice(["tutorial", "bip", "lecture"]), default="tutorial")
@click.option("--brief", type=str, default=None)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def stage_transcribe(file: Path, lang: str, style: str, brief: str | None, output: Path | None):
    """Stage 1: Transcribe a recording.

    \b
    Input:  Recording file (mp4, mov, wav, mp3)
    Output: transcript.json + project.clipflow.yaml
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages import transcribe

    output = output or Path("./clipflow_out")
    spec = ProjectSpec.from_tutorial_args(file=file, lang=lang, style=style, brief=brief, output_dir=output)

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Stage 1: Transcribe[/bold] — {file}")
    transcript = transcribe.run(spec, on_progress=on_progress)
    spec.source.duration = transcript.duration
    spec_path = spec.save()

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Words:      {transcript.word_count}")
    console.print(f"  Duration:   {transcript.duration:.1f}s")
    console.print(f"  Language:   {transcript.lang_detected}")
    console.print(f"  Transcript: {spec.tutorial.transcript_file}")
    console.print(f"  Spec:       {spec_path}")


@stage.command("analyze")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def stage_analyze(project_dir: Path):
    """Stage 2: Analyze transcript structure with LLM.

    \b
    Input:  Project dir containing project.clipflow.yaml + transcript.json
    Output: structure.json (chapters, filler, personality moments)
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages import analyze
    from clipflow.utils.whisper_router import Transcript

    spec = _load_spec(project_dir)
    transcript = Transcript.load(spec.tutorial.transcript_file)

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Stage 2: Analyze[/bold] — {transcript.word_count} words, {transcript.duration:.0f}s")
    structure = analyze.run(spec, transcript, on_progress=on_progress)

    spec.tutorial.chapters = [
        {"title": c.title, "start": c.start, "end": c.end}
        for c in structure.chapters
    ]
    spec.save()

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Chapters:   {len(structure.chapters)}")
    for ch in structure.chapters:
        console.print(f"              [{ch.start:.0f}s-{ch.end:.0f}s] {ch.title}")
    console.print(f"  Filler:     {structure.total_filler_duration:.0f}s across {len(structure.filler_sections)} sections")
    console.print(f"  Personality: {len(structure.personality_moments)} moments")
    console.print(f"  Est. final: {structure.estimated_final_duration:.0f}s")


@stage.command("editorial")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("editorial_json", type=click.Path(exists=True, path_type=Path))
def stage_editorial(project_dir: Path, editorial_json: Path):
    """Stage 2b: Apply an editorial plan (restructure + aggressive cut).

    \b
    The editorial plan is a JSON file produced by the AI agent during
    the session. It specifies which segments to keep, in what order,
    for a specific platform (e.g. xiaohongshu).

    \b
    Input:  Project dir + editorial_plan.json (agent-generated)
    Output: edl.json (overwritten with editorial decisions)

    \b
    Usage:
      # Agent writes editorial_plan.json, then:
      clipflow stage editorial out/ out/editorial_plan.json
      clipflow stage cut out/
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages.editorial import EditorialPlan

    spec = _load_spec(project_dir)
    plan = EditorialPlan.load(editorial_json)

    source_duration = spec.source.duration or 0
    edl = plan.to_edl(source_duration)

    edl_path = spec.tutorial.edl_file or str(Path(spec.output_dir) / "edl.json")
    edl.save(edl_path)
    spec.save()

    console.print(f"[bold]Editorial: {plan.platform}[/bold]")
    console.print(f"  Target:   {plan.target_duration:.0f}s ({plan.target_duration/60:.0f}min)")
    console.print(f"  Actual:   {plan.estimated_duration:.0f}s ({plan.estimated_duration/60:.1f}min)")
    console.print(f"  Segments: {len(plan.segments)}")
    for seg in sorted(plan.segments, key=lambda s: s.position):
        dur = seg.source_end - seg.source_start
        console.print(f"    {seg.position+1}. [{seg.label}] {dur:.0f}s — {seg.reason}")
    console.print(f"\n  Rationale: {plan.cuts_rationale}")
    console.print(f"\n[green]EDL written.[/green] Next: clipflow stage cut {project_dir}")


@stage.command("script")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("script_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output readable script file (default: <project_dir>/insert_script.txt)")
def stage_script(project_dir: Path, script_json: Path, output: Path | None):
    """Generate a readable face-to-camera insert script.

    \b
    The insert script JSON is produced by the AI agent during editorial planning.
    This command converts it to a human-readable recording guide.

    \b
    Input:  Project dir + insert_script.json (agent-generated)
    Output: insert_script.txt (printable recording guide)

    \b
    Usage:
      clipflow stage script out/ out/insert_script.json
    """
    from clipflow.stages.editorial import InsertScript

    script = InsertScript.load(script_json)

    out_dir = Path(project_dir)
    output = output or out_dir / "insert_script.txt"

    readable = script.to_readable()
    output.write_text(readable, encoding="utf-8")

    console.print(f"[bold]Insert Script[/bold] — {len(script.inserts)} face-to-camera inserts")
    console.print(f"  Total recording time: {script.total_insert_time}")
    console.print(f"  Script saved to: {output}")
    console.print()
    console.print(readable)


@stage.command("plan")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def stage_plan(project_dir: Path):
    """Stage 3: Generate edit decision list from analysis.

    \b
    Input:  Project dir with structure.json
    Output: edl.json (keep/cut actions with timestamps)
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages import plan
    from clipflow.stages.analyze import Structure

    spec = _load_spec(project_dir)
    structure = Structure.load(spec.tutorial.structure_file)

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Stage 3: Plan[/bold] — style={spec.tutorial.style}")
    edl = plan.run(spec, structure, on_progress=on_progress)
    spec.save()

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Keep:     {len(edl.keep_actions())} segments, {edl.estimated_output_duration:.0f}s")
    console.print(f"  Cut:      {edl.cut_count} sections, {edl.total_cut_duration:.0f}s removed")
    console.print(f"  Ratio:    {edl.estimated_output_duration / edl.source_duration * 100:.0f}% kept")


@stage.command("cut")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def stage_cut(project_dir: Path):
    """Stage 4: Execute cuts from the EDL.

    \b
    Input:  Project dir with edl.json + source recording
    Output: cut.mp4 (filler removed, segments concatenated)
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages import cut
    from clipflow.stages.plan import EDL

    spec = _load_spec(project_dir)
    edl = EDL.load(spec.tutorial.edl_file)

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Stage 4: Cut[/bold] — {len(edl.keep_actions())} segments to keep")
    result = cut.run(spec, edl, on_progress=on_progress)
    spec.save()

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Output:   {result.file}")
    console.print(f"  Duration: {result.duration:.1f}s")
    console.print(f"  Segments: {result.segments_kept} kept, {result.segments_cut} cut")


@stage.command("compose")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def stage_compose(project_dir: Path):
    """Stage 5: Add captions, chapters, and overlays.

    \b
    Input:  Project dir with cut.mp4 + transcript.json + structure.json + edl.json
    Output: composed.mp4 + captions.ass + chapters.txt
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages import compose
    from clipflow.stages.cut import CutResult
    from clipflow.stages.plan import EDL
    from clipflow.stages.analyze import Structure
    from clipflow.utils.whisper_router import Transcript
    from clipflow.utils.ffmpeg import probe_duration

    spec = _load_spec(project_dir)
    out_dir = Path(spec.output_dir)

    transcript = Transcript.load(spec.tutorial.transcript_file)
    structure = Structure.load(spec.tutorial.structure_file)
    edl = EDL.load(spec.tutorial.edl_file)

    cut_file = out_dir / "cut.mp4"
    cut_result = CutResult(
        file=str(cut_file),
        duration=probe_duration(cut_file),
        segments_kept=len(edl.keep_actions()),
        segments_cut=edl.cut_count,
    )

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Stage 5: Compose[/bold] — captions + chapters")
    result = compose.run(spec, cut_result, transcript, structure, edl, on_progress=on_progress)
    spec.save()

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Output:   {result.file}")
    console.print(f"  Captions: {'yes' if result.has_captions else 'no'}")
    console.print(f"  Chapters: {len(result.chapter_markers)}")
    for ch in result.chapter_markers:
        console.print(f"            {_fmt_time(ch['start'])} {ch['title']}")


@stage.command("render")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def stage_render(project_dir: Path):
    """Stage 6: Render master at target resolution/codec.

    \b
    Input:  Project dir with composed.mp4
    Output: rendered.mp4 (master file at target settings)
    """
    from clipflow.project import ProjectSpec
    from clipflow.stages import render
    from clipflow.stages.compose import ComposeResult

    spec = _load_spec(project_dir)
    out_dir = Path(spec.output_dir)

    composed_file = out_dir / "composed.mp4"
    compose_result = ComposeResult(
        file=str(composed_file),
        has_captions=True,
        has_chapters=True,
        chapter_markers=[],
    )

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Stage 6: Render[/bold] — {spec.render.resolution} {spec.render.codec}")
    result = render.run(spec, compose_result, on_progress=on_progress)
    spec.save()

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Output:     {result.file}")
    console.print(f"  Resolution: {result.width}x{result.height}")
    console.print(f"  Duration:   {result.duration:.1f}s")
    console.print(f"  Size:       {result.file_size_mb:.1f}MB")


@stage.command("export")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--platform", "-p", multiple=True,
              help="Target platforms (youtube, tiktok, instagram, twitter, xiaohongshu, shorts). Repeatable.")
@click.option("--max-duration", type=int, default=None,
              help="Override max duration in seconds (e.g. --max-duration 900 for 15min)")
def stage_export(project_dir: Path, platform: tuple[str, ...], max_duration: int | None):
    """Stage 7: Export platform-specific variants.

    \b
    Input:  Project dir with rendered.mp4
    Output: Platform-specific files + export_manifest.json

    \b
    Examples:
      clipflow stage export out/ -p xiaohongshu
      clipflow stage export out/ -p xiaohongshu --max-duration 900
    """
    from clipflow.project import ProjectSpec, ExportFormat
    from clipflow.stages import export
    from clipflow.stages.render import RenderResult
    from clipflow.stages.analyze import Structure
    from clipflow.utils.ffmpeg import probe_duration, probe_video_info

    spec = _load_spec(project_dir)
    out_dir = Path(spec.output_dir)

    # Override export platforms if specified
    if platform:
        from clipflow.stages.export import PLATFORM_PRESETS
        spec.export.formats = [
            ExportFormat(platform=p, ratio=PLATFORM_PRESETS.get(p, {}).get("ratio", "16:9"))
            for p in platform
        ]

    rendered_file = out_dir / "rendered.mp4"
    info = probe_video_info(rendered_file)
    render_result = RenderResult(
        file=str(rendered_file),
        width=info["width"],
        height=info["height"],
        fps=int(info["fps"]),
        codec=info["codec"],
        duration=probe_duration(rendered_file),
        file_size_mb=rendered_file.stat().st_size / (1024 * 1024),
    )

    structure = Structure.load(spec.tutorial.structure_file)

    # Override max duration if specified
    if max_duration is not None:
        from clipflow.stages.export import PLATFORM_PRESETS
        for fmt in spec.export.formats:
            if fmt.platform in PLATFORM_PRESETS:
                PLATFORM_PRESETS[fmt.platform]["max_duration"] = max_duration

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    dur_note = f", max {max_duration}s" if max_duration else ""
    platforms_str = ", ".join(f.platform for f in spec.export.formats)
    console.print(f"[bold]Stage 7: Export[/bold] — {platforms_str}{dur_note}")
    results = export.run(spec, render_result, structure, on_progress=on_progress)
    spec.save()

    console.print(f"\n[green]Done.[/green]")
    for r in results:
        trunc = " [yellow](truncated)[/yellow]" if r.truncated else ""
        console.print(f"  {r.platform:10s} {r.ratio:5s}  {r.duration:.0f}s  {r.file_size_mb:.1f}MB  {r.file}{trunc}")


@stage.command("subtitle")
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.argument("srt_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output file (default: <input>_subtitled.mp4)")
@click.option("--lang", type=click.Choice(["zh", "en"]), default="zh",
              help="Subtitle language (affects font selection)")
@click.option("--font-size", type=int, default=42, help="Font size in pixels")
@click.option("--bg/--no-bg", default=True, help="Show background box behind text")
def stage_subtitle(video_file: Path, srt_file: Path, output: Path | None,
                   lang: str, font_size: int, bg: bool):
    """Burn subtitles into a video file.

    \b
    Input:  Video file + SRT subtitle file
    Output: Video with burned-in subtitles

    \b
    Examples:
      clipflow stage subtitle out/xiaohongshu_16x9.mp4 out/captions_zh.srt
      clipflow stage subtitle video.mp4 subs.srt --lang en --font-size 36 --no-bg
    """
    from clipflow.utils.subtitle_burn import burn_subtitles

    if output is None:
        output = video_file.parent / f"{video_file.stem}_subtitled{video_file.suffix}"

    # Font selection by language
    font_map = {
        "zh": "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "en": "/System/Library/Fonts/Helvetica.ttc",
    }
    font_path = font_map.get(lang, font_map["en"])

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    console.print(f"[bold]Subtitle[/bold] — {lang}, {font_size}px, bg={'yes' if bg else 'no'}")
    burn_subtitles(
        video_path=video_file,
        srt_path=srt_file,
        output_path=output,
        font_path=font_path,
        font_size=font_size,
        bg_color="#000000" if bg else None,
        on_progress=on_progress,
    )

    size_mb = output.stat().st_size / (1024 * 1024)
    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Output: {output}")
    console.print(f"  Size:   {size_mb:.1f}MB")


@stage.command("chapters")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("chapters_json", type=click.Path(exists=True, path_type=Path))
def stage_chapters(project_dir: Path, chapters_json: Path):
    """Generate chapter markers for social media platforms.

    \b
    The chapters JSON is produced by the AI agent. Each entry has a title
    and start time in seconds. This command outputs a copy-pasteable
    chapter list for xiaohongshu, YouTube, etc.

    \b
    Input:  Project dir + chapters.json
    Output: chapters.txt (MM:SS Title format, ready to paste)

    \b
    Usage:
      clipflow stage chapters out/ out/chapters.json
    """
    import json

    chapters = json.loads(chapters_json.read_text())
    out_dir = Path(project_dir)

    def fmt(s):
        m, sec = int(s // 60), int(s % 60)
        return f"{m:02d}:{sec:02d}"

    lines = [f"{fmt(ch['start'])} {ch['title']}" for ch in chapters]
    txt = "\n".join(lines)

    txt_path = out_dir / "chapters.txt"
    txt_path.write_text(txt, encoding="utf-8")

    console.print(f"[bold]Chapters[/bold] — {len(chapters)} markers")
    console.print()
    for line in lines:
        console.print(f"  {line}")
    console.print(f"\n  Saved: {txt_path}")


@stage.command("copy")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("copy_json", type=click.Path(exists=True, path_type=Path))
def stage_copy(project_dir: Path, copy_json: Path):
    """Save social media post copy to readable format.

    \b
    The post copy JSON is produced by the AI agent during editorial planning.
    This command saves it as both JSON and a readable TXT file.

    \b
    Input:  Project dir + post_copy.json (agent-generated)
    Output: post_copy.txt (ready to paste into xiaohongshu/tiktok)

    \b
    Usage:
      clipflow stage copy out/ out/post_copy.json
    """
    from clipflow.stages.copywriting import PostCopy

    copy = PostCopy.load(copy_json)
    out_dir = Path(project_dir)

    txt_path = out_dir / "post_copy.txt"
    txt_path.write_text(copy.to_readable(), encoding="utf-8")

    console.print(f"[bold]{copy.platform.upper()} Post Copy[/bold]")
    console.print(f"  Title: {copy.title}")
    console.print(f"  Hook:  {copy.hook_line}")
    console.print(f"  Tags:  {' '.join('#' + t for t in copy.hashtags)}")
    console.print(f"  Body:  {len(copy.body)} chars")
    console.print(f"\n  Saved: {txt_path}")
    console.print(f"\n{copy.to_readable()}")


@stage.command("cover")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--title-zh", type=str, required=True, help="Chinese title text")
@click.option("--title-en", type=str, required=True, help="English title text")
@click.option("--subtitle-zh", type=str, default=None, help="Chinese subtitle")
@click.option("--subtitle-en", type=str, default=None, help="English subtitle")
@click.option("--tag", type=str, default=None, help="Tag pill text (e.g. 'EP03')")
@click.option("--style", type=click.Choice(["bold-center", "split-top", "gradient-bar"]),
              default="bold-center", help="Cover layout style")
@click.option("--platform", type=click.Choice(["xiaohongshu", "tiktok", "reels", "youtube"]),
              default="xiaohongshu", help="Target platform (determines size)")
@click.option("--accent", type=str, default="#FF6B35", help="Accent color hex")
@click.option("--frame", type=click.Path(exists=True, path_type=Path), default=None,
              help="Background image/photo (default: extract from video)")
@click.option("--frame-time", type=float, default=5.0,
              help="Timestamp to extract frame from video (if no --frame)")
def stage_cover(project_dir: Path, title_zh: str, title_en: str,
                subtitle_zh: str | None, subtitle_en: str | None,
                tag: str | None, style: str, platform: str, accent: str,
                frame: Path | None, frame_time: float):
    """Generate a cover image for social media.

    \b
    Creates eye-catching cover images with bilingual text overlay.
    Three styles: bold-center, split-top, gradient-bar.

    \b
    Examples:
      clipflow stage cover out/ --title-zh "AI帮我剪视频" --title-en "AI Edits My Video"
      clipflow stage cover out/ --title-zh "..." --title-en "..." --style gradient-bar
      clipflow stage cover out/ --title-zh "..." --title-en "..." --frame photo.jpg
    """
    from clipflow.stages.cover import generate_cover, CoverConfig, extract_best_frame

    out_dir = Path(project_dir)

    if frame is None:
        # Try to find a video to extract from
        for candidate in ["spliced.mp4", "cut.mp4", "rendered.mp4"]:
            vid = out_dir / candidate
            if vid.exists():
                frame = out_dir / "cover_frame.jpg"
                extract_best_frame(vid, frame, frame_time)
                break

    config = CoverConfig(
        title_zh=title_zh, title_en=title_en,
        subtitle_zh=subtitle_zh, subtitle_en=subtitle_en,
        tag=tag, platform=platform, style=style, accent_color=accent,
    )

    output = out_dir / f"cover_{style}_{platform}.jpg"
    generate_cover(config, background_image=frame, output_path=output)

    console.print(f"[green]Done.[/green]")
    console.print(f"  Style:    {style}")
    console.print(f"  Platform: {platform}")
    console.print(f"  Output:   {output}")


@stage.command("splice")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--inserts-dir", type=click.Path(exists=True, path_type=Path), default=None,
              help="Directory containing insert_01.mp4 ... insert_N.mp4")
def stage_splice(project_dir: Path, inserts_dir: Path | None):
    """Splice screen segments with face-to-camera inserts.

    \b
    Reads the splice_plan from insert_script.json and interleaves
    screen segments (from clipflow_out/segments/) with face inserts
    (from inserts/ folder) into a single spliced video.

    \b
    Input:  Project dir with segments/ + inserts/ + insert_script.json
    Output: spliced.mp4

    \b
    Examples:
      clipflow stage splice out/
      clipflow stage splice out/ --inserts-dir ../inserts/
    """
    import json
    from clipflow.utils.ffmpeg import concat_files, probe_duration

    out_dir = Path(project_dir)
    if inserts_dir is None:
        # Try common locations
        for candidate in [out_dir.parent / "inserts", out_dir / "inserts"]:
            if candidate.exists():
                inserts_dir = candidate
                break
    if inserts_dir is None:
        raise click.ClickException("No inserts directory found. Use --inserts-dir.")

    script_file = out_dir / "insert_script.json"
    if not script_file.exists():
        raise click.ClickException(f"No insert_script.json found in {out_dir}")

    script = json.loads(script_file.read_text())
    if "splice_plan" not in script:
        raise click.ClickException("insert_script.json has no splice_plan. Regenerate with editorial stage.")

    segments_dir = out_dir / "segments"
    sequence = script["splice_plan"]["sequence"]

    file_list = []
    for item in sequence:
        if item["type"] == "screen":
            f = segments_dir / f"seg_{item['segment']-1:04d}.mp4"
            if not f.exists():
                raise click.ClickException(f"Missing segment: {f}")
            file_list.append(f)
            console.print(f"  [dim]screen[/dim]  {f.name} ({probe_duration(f):.0f}s)  {item['label']}")
        else:
            f = inserts_dir / f"insert_{item['insert']:02d}.mp4"
            if not f.exists():
                raise click.ClickException(f"Missing insert: {f}. Record and save as insert_{item['insert']:02d}.mp4")
            file_list.append(f)
            console.print(f"  [bold]face[/bold]    {f.name} ({probe_duration(f):.0f}s)  {item['label']}")

    spliced = out_dir / "spliced.mp4"
    console.print(f"\n  Splicing {len(file_list)} files...")
    concat_files(file_list, spliced)
    dur = probe_duration(spliced)
    size = spliced.stat().st_size / (1024 * 1024)

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Output:   {spliced}")
    console.print(f"  Duration: {dur:.0f}s ({dur/60:.1f}min)")
    console.print(f"  Size:     {size:.1f}MB")


@stage.command("speed")
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--rate", "-r", type=float, default=1.5, help="Speed multiplier (default: 1.5)")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output file (default: <input>_<rate>x.mp4)")
def stage_speed(video_file: Path, rate: float, output: Path | None):
    """Apply speed multiplier to a video.

    \b
    Adjusts both video and audio speed. Common rates:
      1.25x — slightly faster, still natural
      1.5x  — noticeably faster, good for tutorials
      2.0x  — double speed, for montages

    \b
    Examples:
      clipflow stage speed spliced.mp4
      clipflow stage speed spliced.mp4 --rate 1.25
      clipflow stage speed spliced.mp4 --rate 2.0 -o fast.mp4
    """
    import subprocess
    from clipflow.utils.ffmpeg import probe_duration

    if output is None:
        rate_str = f"{rate:.1f}".replace(".", "_")
        output = video_file.parent / f"{video_file.stem}_{rate_str}x{video_file.suffix}"

    console.print(f"[bold]Speed[/bold] — {rate}x")

    # Build audio tempo filter chain (atempo only supports 0.5-2.0 per instance)
    audio_filters = []
    remaining = rate
    while remaining > 2.0:
        audio_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        audio_filters.append("atempo=0.5")
        remaining /= 0.5
    audio_filters.append(f"atempo={remaining:.4f}")
    atempo_chain = ",".join(audio_filters)

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_file),
            "-filter_complex",
            f"[0:v]setpts=PTS/{rate}[v];[0:a]{atempo_chain}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac",
            str(output),
        ],
        capture_output=True, check=True,
    )

    dur = probe_duration(output)
    size = output.stat().st_size / (1024 * 1024)

    console.print(f"\n[green]Done.[/green]")
    console.print(f"  Output:   {output}")
    console.print(f"  Duration: {dur:.0f}s ({dur/60:.1f}min)")
    console.print(f"  Size:     {size:.1f}MB")


# ---------------------------------------------------------------------------
# Resume from any stage
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--from", "from_stage", type=click.Choice(STAGES), default=None,
              help="Stage to resume from (default: auto-detect)")
def resume(project_dir: Path, from_stage: str | None):
    """Resume a pipeline from a specific stage.

    \b
    Reads the project spec and intermediate files to determine where
    to pick up. Use --from to force starting at a specific stage.

    \b
    Examples:
      clipflow resume out/                  # auto-detect where to resume
      clipflow resume out/ --from plan      # re-run from plan stage onwards
      clipflow resume out/ --from compose   # redo compose with tweaked captions
    """
    from clipflow.project import ProjectSpec

    spec = _load_spec(project_dir)

    if from_stage is None:
        from_stage = _detect_resume_point(spec)
        console.print(f"[dim]Auto-detected resume point: {from_stage}[/dim]")

    console.print(Panel(
        f"Pipeline:  {spec.pipeline}\n"
        f"Source:    {spec.source.file}\n"
        f"Style:     {spec.tutorial.style}\n"
        f"Resuming:  [bold]{from_stage}[/bold] → export",
        title="[bold]Resuming pipeline[/bold]",
        border_style="green",
    ))

    _run_from_stage(spec, from_stage)
    spec.save()
    console.print("\n[bold green]Pipeline complete.[/bold green]")


# ---------------------------------------------------------------------------
# Inspect project state
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def status(project_dir: Path):
    """Show the status of a ClipFlow project.

    \b
    Reads the project spec and checks which intermediate files exist
    to show pipeline progress.
    """
    from clipflow.project import ProjectSpec

    spec = _load_spec(project_dir)
    out_dir = Path(spec.output_dir)

    table = Table(title=f"ClipFlow Project — {spec.source.file}")
    table.add_column("Stage", style="bold")
    table.add_column("Status")
    table.add_column("Output")

    checks = [
        ("transcribe", spec.tutorial.transcript_file, "transcript.json"),
        ("analyze", spec.tutorial.structure_file, "structure.json"),
        ("plan", spec.tutorial.edl_file, "edl.json"),
        ("cut", str(out_dir / "cut.mp4"), "cut.mp4"),
        ("compose", str(out_dir / "composed.mp4"), "composed.mp4"),
        ("render", str(out_dir / "rendered.mp4"), "rendered.mp4"),
        ("export", str(out_dir / "export_manifest.json"), "export_manifest.json"),
    ]

    resume_point = None
    for stage_name, file_path, label in checks:
        if file_path and Path(file_path).exists():
            size = Path(file_path).stat().st_size
            if size > 1024 * 1024:
                size_str = f"{size / 1024 / 1024:.1f}MB"
            elif size > 1024:
                size_str = f"{size / 1024:.0f}KB"
            else:
                size_str = f"{size}B"
            table.add_row(stage_name, "[green]done[/green]", f"{label} ({size_str})")
        else:
            if resume_point is None:
                resume_point = stage_name
                table.add_row(stage_name, "[yellow]next[/yellow]", f"{label}")
            else:
                table.add_row(stage_name, "[dim]pending[/dim]", f"{label}")

    console.print(table)

    if resume_point:
        console.print(f"\nResume with: [bold]clipflow resume {project_dir} --from {resume_point}[/bold]")
    else:
        console.print("\n[green]All stages complete.[/green]")


# ---------------------------------------------------------------------------
# UGC (v2 stub)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("brief_file", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def ugc(ctx, brief_file: Path):
    """[v2.0] Run the UGC/viral pipeline from a product brief."""
    console.print(Panel(
        "[bold yellow]UGC pipeline is planned for v2.0[/bold yellow]\n\n"
        "The project spec, template system, render engine, and export layer\n"
        "are already designed to support this pipeline.\n\n"
        "See: src/clipflow/stages_v2/ for interface contracts.",
        title="ClipFlow v2.0 — coming soon",
        border_style="yellow",
    ))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@main.group()
def config():
    """Manage ClipFlow configuration."""
    pass


@config.command("init")
@click.option("--anthropic-key", prompt="Anthropic API key", hide_input=True,
              help="Your Anthropic API key")
@click.option("--whisper-model", type=click.Choice(["tiny", "base", "small", "medium", "large-v3"]),
              default="base", help="Default Whisper model size")
@click.option("--default-lang", type=click.Choice(["en", "zh", "zh-en"]),
              default="en", help="Default language")
def config_init(anthropic_key: str, whisper_model: str, default_lang: str):
    """Initialize ClipFlow configuration."""
    from clipflow.config import init_config
    init_config(
        anthropic_key=anthropic_key,
        whisper_model=whisper_model,
        default_lang=default_lang,
    )
    console.print("[green]Done.[/green] Configuration saved to ~/.clipflow/config.yaml")


@config.command("show")
def config_show():
    """Show current configuration."""
    from clipflow.config import load_config
    cfg = load_config()
    if cfg:
        console.print(Panel(str(cfg), title="Current config"))
    else:
        console.print("[yellow]No config found. Run: clipflow config init[/yellow]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_spec(project_dir: Path):
    """Load project spec from a directory."""
    from clipflow.project import ProjectSpec

    spec_file = project_dir / "project.clipflow.yaml"
    if not spec_file.exists():
        # Check if project_dir IS the output dir
        for candidate in [project_dir, project_dir.parent]:
            candidate_spec = candidate / "project.clipflow.yaml"
            if candidate_spec.exists():
                return ProjectSpec.load(candidate_spec)

        raise click.ClickException(
            f"No project.clipflow.yaml found in {project_dir}\n"
            f"Run 'clipflow stage transcribe <file>' first to create a project."
        )

    return ProjectSpec.load(spec_file)


def _detect_resume_point(spec) -> str:
    """Detect which stage to resume from based on existing files."""
    out_dir = Path(spec.output_dir)

    checks = [
        ("export", out_dir / "export_manifest.json"),
        ("render", out_dir / "rendered.mp4"),
        ("compose", out_dir / "composed.mp4"),
        ("cut", out_dir / "cut.mp4"),
        ("plan", spec.tutorial.edl_file),
        ("analyze", spec.tutorial.structure_file),
        ("transcribe", spec.tutorial.transcript_file),
    ]

    # Find the last completed stage, resume from the next one
    for i, (stage_name, file_path) in enumerate(checks):
        if file_path and Path(file_path).exists():
            # This stage is done — resume from the next one
            stage_idx = STAGES.index(stage_name)
            if stage_idx + 1 < len(STAGES):
                return STAGES[stage_idx + 1]
            return stage_name  # all done, re-run last

    return "transcribe"  # nothing done yet


def _run_from_stage(spec, from_stage: str):
    """Run pipeline stages starting from a given stage."""
    from clipflow.stages import transcribe, analyze, plan, cut, compose, render, export
    from clipflow.stages.plan import EDL
    from clipflow.stages.cut import CutResult
    from clipflow.stages.compose import ComposeResult
    from clipflow.stages.render import RenderResult
    from clipflow.stages.analyze import Structure
    from clipflow.utils.whisper_router import Transcript
    from clipflow.utils.ffmpeg import probe_duration, probe_video_info

    out_dir = Path(spec.output_dir)
    start_idx = STAGES.index(from_stage)

    def on_progress(stage, msg, pct):
        console.print(f"  [dim]{msg}[/dim]")

    # Load existing artifacts for stages we're skipping
    transcript_obj = None
    structure_obj = None
    edl_obj = None
    cut_obj = None
    compose_obj = None
    render_obj = None

    if start_idx > 0 and spec.tutorial.transcript_file and Path(spec.tutorial.transcript_file).exists():
        transcript_obj = Transcript.load(spec.tutorial.transcript_file)
    if start_idx > 1 and spec.tutorial.structure_file and Path(spec.tutorial.structure_file).exists():
        structure_obj = Structure.load(spec.tutorial.structure_file)
    if start_idx > 2 and spec.tutorial.edl_file and Path(spec.tutorial.edl_file).exists():
        edl_obj = EDL.load(spec.tutorial.edl_file)
    if start_idx > 3 and (out_dir / "cut.mp4").exists():
        cut_obj = CutResult(
            file=str(out_dir / "cut.mp4"),
            duration=probe_duration(out_dir / "cut.mp4"),
            segments_kept=len(edl_obj.keep_actions()) if edl_obj else 0,
            segments_cut=edl_obj.cut_count if edl_obj else 0,
        )
    if start_idx > 4 and (out_dir / "composed.mp4").exists():
        compose_obj = ComposeResult(
            file=str(out_dir / "composed.mp4"),
            has_captions=True, has_chapters=True, chapter_markers=[],
        )
    if start_idx > 5 and (out_dir / "rendered.mp4").exists():
        info = probe_video_info(out_dir / "rendered.mp4")
        render_obj = RenderResult(
            file=str(out_dir / "rendered.mp4"),
            width=info["width"], height=info["height"],
            fps=int(info["fps"]), codec=info["codec"],
            duration=probe_duration(out_dir / "rendered.mp4"),
            file_size_mb=(out_dir / "rendered.mp4").stat().st_size / (1024 * 1024),
        )

    # Run stages
    for stage_name in STAGES[start_idx:]:
        console.print(f"\n[bold]Running: {stage_name}[/bold]")

        if stage_name == "transcribe":
            transcript_obj = transcribe.run(spec, on_progress=on_progress)
            spec.source.duration = transcript_obj.duration

        elif stage_name == "analyze":
            structure_obj = analyze.run(spec, transcript_obj, on_progress=on_progress)
            spec.tutorial.chapters = [
                {"title": c.title, "start": c.start, "end": c.end}
                for c in structure_obj.chapters
            ]

        elif stage_name == "plan":
            edl_obj = plan.run(spec, structure_obj, on_progress=on_progress)

        elif stage_name == "cut":
            cut_obj = cut.run(spec, edl_obj, on_progress=on_progress)

        elif stage_name == "compose":
            compose_obj = compose.run(
                spec, cut_obj, transcript_obj, structure_obj, edl_obj,
                on_progress=on_progress,
            )

        elif stage_name == "render":
            render_obj = render.run(spec, compose_obj, on_progress=on_progress)

        elif stage_name == "export":
            export.run(spec, render_obj, structure_obj, on_progress=on_progress)


def _fmt_time(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


if __name__ == "__main__":
    main()
