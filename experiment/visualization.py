"""GIF and MP4 visualization of daily utilization by solver method."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

from .contracts import MethodRun


class MissingVisualizationDependency(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyPoint:
    active_blocks: int
    overall_utilization: float
    peak_yard_utilization: float


METHOD_COLORS = {
    "or": "#2563EB",
    "sa": "#EA580C",
    "rl": "#16A34A",
}


def load_daily_points(path: Path) -> Dict[date, DailyPoint]:
    grouped: Dict[date, Dict[str, object]] = defaultdict(
        lambda: {"active": 0, "used": 0.0, "capacity": 0.0, "peak": 0.0}
    )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            day = date.fromisoformat(row["date"])
            values = grouped[day]
            values["active"] = int(values["active"]) + int(row["active_blocks"])
            values["used"] = float(values["used"]) + float(row["used_area_m2"])
            values["capacity"] = float(values["capacity"]) + float(
                row["usable_area_m2"]
            )
            values["peak"] = max(float(values["peak"]), float(row["utilization"]))
    return {
        day: DailyPoint(
            active_blocks=int(values["active"]),
            overall_utilization=(
                float(values["used"]) / float(values["capacity"])
                if float(values["capacity"])
                else 0.0
            ),
            peak_yard_utilization=float(values["peak"]),
        )
        for day, values in grouped.items()
    }


def _load_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as exc:
        raise MissingVisualizationDependency(
            "GIF rendering requires Pillow: python -m pip install Pillow"
        ) from exc
    return Image, ImageDraw, ImageFont


def _draw_bar(draw, box, ratio: float, color: str, background: str = "#E5E7EB"):
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=7, fill=background)
    fill_right = left + int((right - left) * max(0.0, min(1.0, ratio)))
    if fill_right > left:
        draw.rounded_rectangle((left, top, fill_right, bottom), radius=7, fill=color)


def build_frames(
    runs: Sequence[MethodRun],
    comparison_rows: Sequence[Mapping[str, object]],
    frame_step_days: int,
):
    Image, ImageDraw, ImageFont = _load_pillow()
    successful = [run for run in runs if run.utilization_path.exists()]
    if not successful:
        raise ValueError("No daily utilization output is available to visualize")

    series = {run.method: load_daily_points(run.utilization_path) for run in successful}
    all_days = sorted({day for points in series.values() for day in points})
    selected_days = all_days[::frame_step_days]
    if selected_days[-1] != all_days[-1]:
        selected_days.append(all_days[-1])
    cost_by_method = {
        str(row["method"]): row.get("total_cost", "") for row in comparison_rows
    }

    width = 960
    row_height = 125
    height = 150 + row_height * len(successful)
    font = ImageFont.load_default()
    frames = []
    for day in selected_days:
        image = Image.new("RGB", (width, height), "#F8FAFC")
        draw = ImageDraw.Draw(image)
        draw.text((36, 26), "Stockyard solver comparison", fill="#0F172A", font=font)
        draw.text((36, 54), f"Date: {day.isoformat()}", fill="#334155", font=font)
        draw.text(
            (36, 82),
            "Overall utilization and busiest-yard utilization",
            fill="#64748B",
            font=font,
        )

        for index, run in enumerate(successful):
            top = 125 + index * row_height
            point = series[run.method].get(day, DailyPoint(0, 0.0, 0.0))
            color = METHOD_COLORS.get(run.method, "#475569")
            total_cost = cost_by_method.get(run.method, "")
            cost_text = f"{float(total_cost):,.1f}" if total_cost != "" else "n.a."
            draw.text(
                (36, top),
                f"{run.method.upper()}   cost={cost_text}   active={point.active_blocks}",
                fill="#0F172A",
                font=font,
            )
            draw.text((36, top + 30), "overall", fill="#475569", font=font)
            _draw_bar(
                draw,
                (125, top + 28, 760, top + 46),
                point.overall_utilization,
                color,
            )
            draw.text(
                (775, top + 30),
                f"{point.overall_utilization:.1%}",
                fill="#334155",
                font=font,
            )
            draw.text((36, top + 68), "peak yard", fill="#475569", font=font)
            peak_color = "#DC2626" if point.peak_yard_utilization >= 0.85 else color
            _draw_bar(
                draw,
                (125, top + 66, 760, top + 84),
                point.peak_yard_utilization,
                peak_color,
            )
            draw.text(
                (775, top + 68),
                f"{point.peak_yard_utilization:.1%}",
                fill="#334155",
                font=font,
            )
        frames.append(image)
    return frames


def write_gif(frames, path: Path, fps: float) -> None:
    duration_ms = max(20, round(1_000 / fps))
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )


def write_mp4(frames, path: Path, fps: float) -> None:
    try:
        import imageio_ffmpeg
    except ModuleNotFoundError as exc:
        raise MissingVisualizationDependency(
            "MP4 rendering requires imageio-ffmpeg: "
            "python -m pip install imageio-ffmpeg"
        ) from exc

    width, height = frames[0].size
    writer = imageio_ffmpeg.write_frames(
        str(path),
        (width, height),
        fps=fps,
        codec="libx264",
        pix_fmt_in="rgb24",
        output_params=("-pix_fmt", "yuv420p", "-movflags", "+faststart"),
    )
    writer.send(None)
    try:
        for frame in frames:
            writer.send(frame.convert("RGB").tobytes())
    finally:
        writer.close()


def render_visualizations(
    run_dir: Path,
    runs: Sequence[MethodRun],
    comparison_rows: Sequence[Mapping[str, object]],
    output_format: str,
    fps: float,
    frame_step_days: int,
) -> List[Path]:
    frames = build_frames(runs, comparison_rows, frame_step_days)
    outputs: List[Path] = []
    if output_format in ("gif", "both"):
        gif_path = run_dir / "daily_utilization_comparison.gif"
        write_gif(frames, gif_path, fps)
        outputs.append(gif_path)
    if output_format in ("mp4", "both"):
        mp4_path = run_dir / "daily_utilization_comparison.mp4"
        write_mp4(frames, mp4_path, fps)
        outputs.append(mp4_path)
    return outputs
