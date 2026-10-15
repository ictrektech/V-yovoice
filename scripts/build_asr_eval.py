#!/usr/bin/env python3
"""Build an utterance-level eval set from a TextGrid + session audio file.

Supports single-tier and multi-speaker TextGrids; picked utterances never
overlap in time so each clip maps to exactly one reference interval.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

raw_dir = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
sample_n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
out_dir.mkdir(parents=True, exist_ok=True)

grid_path = next(raw_dir.glob("*.TextGrid"))
wav_path = next(p for p in raw_dir.iterdir() if p.suffix.lower() in {".wav", ".flac"})
text = grid_path.read_text(encoding="utf-8")

intervals: list[tuple[float, float, str]] = []
for block in re.finditer(
    r"intervals \[\d+\]:\s*\n\s*xmin = ([\d.]+)\s*\n\s*xmax = ([\d.]+)\s*\n\s*text = \"(.*?)\"\s*\n", text
):
    xmin, xmax, utterance = float(block.group(1)), float(block.group(2)), block.group(3).strip()
    if utterance and 2.0 <= (xmax - xmin) <= 25.0:
        intervals.append((xmin, xmax, utterance))
intervals.sort(key=lambda item: item[0])

# 均匀抽样, 但被选中的语句之间不允许时间重叠(多说话人层级会给出重叠区间)
picked: list[tuple[float, float, str]] = []
step = max(1, len(intervals) // sample_n)
for index in range(0, len(intervals), step):
    xmin, xmax, utterance = intervals[index]
    if picked and xmin < picked[-1][1]:
        continue
    picked.append((xmin, xmax, utterance))
    if len(picked) >= sample_n:
        break

pad = 0.15
manifest = []
for index, (xmin, xmax, utterance) in enumerate(picked):
    clip = out_dir / f"utt_{index:03d}.wav"
    start = max(0.0, xmin - pad)
    duration = (xmax - xmin) + 2 * pad
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(wav_path),
         "-ac", "1", "-ar", "16000", str(clip)],
        check=True,
    )
    manifest.append({"id": clip.stem, "wav": str(clip), "ref": utterance, "start": xmin, "end": xmax})

(out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
total_chars = sum(len(m["ref"]) for m in manifest)
print(f"wav={wav_path.name} intervals={len(intervals)} picked={len(manifest)} ref_chars={total_chars}")
