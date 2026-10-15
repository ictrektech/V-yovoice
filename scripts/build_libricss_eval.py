#!/usr/bin/env python3
"""Build a LibriCSS eval manifest from meeting_info.txt (recording timeline) + raw_recording.wav."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

session_dir = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
sample_n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
out_dir.mkdir(parents=True, exist_ok=True)

recording = session_dir / "record" / "raw_recording.wav"
info_path = session_dir / "transcription" / "meeting_info.txt"

segments: list[tuple[float, float, str]] = []
lines = info_path.read_text(encoding="utf-8").splitlines()
for line in lines[1:]:  # first line is the header
    parts = line.split(None, 4)
    if len(parts) != 5:
        continue
    start, end, utterance = float(parts[0]), float(parts[1]), parts[4].strip()
    if 2.0 <= (end - start) <= 25.0 and utterance:
        segments.append((start, end, utterance))
segments.sort(key=lambda item: item[0])

picked: list[tuple[float, float, str]] = []
step = max(1, len(segments) // sample_n)
for index in range(0, len(segments), step):
    start, end, utterance = segments[index]
    if picked and start < picked[-1][1]:
        continue
    picked.append((start, end, utterance))
    if len(picked) >= sample_n:
        break

pad = 0.15
manifest = []
for index, (start, end, utterance) in enumerate(picked):
    clip = out_dir / f"utt_{index:03d}.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{max(0.0, start - pad):.3f}", "-t", f"{(end - start) + 2 * pad:.3f}",
         "-i", str(recording), "-ac", "1", "-ar", "16000", str(clip)],
        check=True,
    )
    manifest.append({"id": clip.stem, "wav": str(clip), "ref": utterance, "start": start, "end": end})

(out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"recording={recording.name} segments={len(segments)} picked={len(manifest)}")
