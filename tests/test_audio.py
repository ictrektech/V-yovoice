from __future__ import annotations

import numpy as np

from vvoice.audio import decode_audio


def test_decode_wav_uses_distinct_source_and_target(monkeypatch) -> None:
    command: list[str] = []

    def fake_run(args, **_kwargs) -> None:
        command.extend(args)

    monkeypatch.setattr("vvoice.audio.subprocess.run", fake_run)
    monkeypatch.setattr(
        "vvoice.audio.sf.read",
        lambda *_args, **_kwargs: (np.asarray([0.0], dtype=np.float32), 16000),
    )

    samples, rate = decode_audio(b"wav", "recording.wav")

    assert command[command.index("-i") + 1].endswith("/input.wav")
    assert command[-1].endswith("/decoded.wav")
    assert command[command.index("-i") + 1] != command[-1]
    assert samples.dtype == np.float32
    assert rate == 16000
