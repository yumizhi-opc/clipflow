"""Project spec — the single source of truth for a ClipFlow run.

Every pipeline (tutorial v1, ugc v2) reads and writes a .clipflow.yaml project file.
An AI agent can read this file, modify it, and re-render — this is what makes
ClipFlow agent-native.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import yaml

from clipflow.utils.ffmpeg import probe_duration


@dataclass
class SourceSpec:
    file: str
    duration: float | None = None
    lang: str = "en"

    def resolve_duration(self) -> float:
        if self.duration is None:
            self.duration = probe_duration(self.file)
        return self.duration


@dataclass
class TutorialSpec:
    style: str = "tutorial"
    brief: str | None = None
    broll_dir: str | None = None
    transcript_file: str | None = None
    structure_file: str | None = None
    edl_file: str | None = None
    chapters: list[dict] = field(default_factory=list)


@dataclass
class UGCSpec:
    brief_file: str | None = None
    hook_style: str | None = None
    template: str | None = None
    assets_manifest: str | None = None
    voice: str | None = None
    music: str | None = None
    variants: list[dict] = field(default_factory=list)


@dataclass
class RenderSpec:
    resolution: str = "1080p"
    fps: int = 30
    codec: str = "h264"


@dataclass
class ExportFormat:
    platform: str
    ratio: str
    file: str | None = None


@dataclass
class ExportSpec:
    formats: list[ExportFormat] = field(default_factory=lambda: [
        ExportFormat(platform="youtube", ratio="16:9"),
    ])


@dataclass
class BrandSpec:
    logo: str | None = None
    colors: dict = field(default_factory=lambda: {"primary": "#1a1a1a", "accent": "#0ea5e9"})
    font: str | None = None
    watermark: str | None = None


RESOLUTION_MAP = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}


@dataclass
class ProjectSpec:
    version: str = "1.0"
    pipeline: str = "tutorial"

    source: SourceSpec = field(default_factory=lambda: SourceSpec(file=""))
    tutorial: TutorialSpec = field(default_factory=TutorialSpec)
    ugc: UGCSpec = field(default_factory=UGCSpec)
    render: RenderSpec = field(default_factory=RenderSpec)
    export: ExportSpec = field(default_factory=ExportSpec)
    brand: BrandSpec = field(default_factory=BrandSpec)

    output_dir: str = "./clipflow_out"

    @property
    def render_width(self) -> int:
        return RESOLUTION_MAP.get(self.render.resolution, (1920, 1080))[0]

    @property
    def render_height(self) -> int:
        return RESOLUTION_MAP.get(self.render.resolution, (1920, 1080))[1]

    @classmethod
    def from_tutorial_args(
        cls,
        file: Path,
        lang: str = "en",
        style: str = "tutorial",
        brief: str | None = None,
        broll: Path | None = None,
        brand: Path | None = None,
        output_dir: Path = Path("./clipflow_out"),
    ) -> ProjectSpec:
        spec = cls(
            pipeline="tutorial",
            source=SourceSpec(file=str(file), lang=lang),
            tutorial=TutorialSpec(
                style=style,
                brief=brief,
                broll_dir=str(broll) if broll else None,
                transcript_file=str(output_dir / "transcript.json"),
                structure_file=str(output_dir / "structure.json"),
                edl_file=str(output_dir / "edl.json"),
            ),
            output_dir=str(output_dir),
        )

        if brand:
            brand_data = yaml.safe_load(brand.read_text()) or {}
            spec.brand = BrandSpec(**{k: v for k, v in brand_data.items()
                                     if k in BrandSpec.__dataclass_fields__})

        return spec

    @classmethod
    def load(cls, path: Path) -> ProjectSpec:
        data = yaml.safe_load(path.read_text())
        return cls(
            version=data.get("version", "1.0"),
            pipeline=data.get("pipeline", "tutorial"),
            source=SourceSpec(**data.get("source", {"file": ""})),
            tutorial=TutorialSpec(**data.get("tutorial", {})),
            ugc=UGCSpec(**data.get("ugc", {})),
            render=RenderSpec(**data.get("render", {})),
            export=ExportSpec(
                formats=[ExportFormat(**f) for f in data.get("export", {}).get("formats", [])]
            ),
            brand=BrandSpec(**data.get("brand", {})),
            output_dir=data.get("output_dir", "./clipflow_out"),
        )

    def save(self, path: Path | None = None) -> Path:
        path = path or Path(self.output_dir) / "project.clipflow.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._to_dict()
        path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False))
        return path

    def _to_dict(self) -> dict:
        return {
            "version": self.version,
            "pipeline": self.pipeline,
            "source": asdict(self.source),
            "tutorial": asdict(self.tutorial),
            "ugc": asdict(self.ugc),
            "render": asdict(self.render),
            "export": {"formats": [asdict(f) for f in self.export.formats]},
            "brand": asdict(self.brand),
            "output_dir": self.output_dir,
        }

    def describe(self) -> str:
        lines = [
            f"Pipeline:    {self.pipeline}",
            f"Source:      {self.source.file}",
            f"Language:    {self.source.lang}",
            f"Style:       {self.tutorial.style}",
        ]
        if self.tutorial.brief:
            lines.append(f"Brief:       {self.tutorial.brief}")
        if self.tutorial.broll_dir:
            lines.append(f"B-roll:      {self.tutorial.broll_dir}")
        lines.append(f"Output:      {self.output_dir}")
        lines.append(f"Export:      {', '.join(f.platform + ' ' + f.ratio for f in self.export.formats)}")
        return "\n".join(lines)
