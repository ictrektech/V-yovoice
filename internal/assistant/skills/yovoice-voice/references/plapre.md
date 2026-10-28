# Plapre 3 (plapre-3-bf16 / -f32)

Apply with `update_work` {"id","settings":{...}}. Requires audio.cpp v0.9.3. Danish only, mono 24 kHz.

- `voiceMode=design` (default): built-in voice; `speaker` is `tor` (default), `ida`, `liv`, `ask`, or `kaj`. Do not set `voiceId`.
- `voiceMode=clone`: requires `voiceId`; `referenceText` (max 2000 chars) is optional and should exactly match the recording.
- `seed`: 0-2147483647; omit or -1 for random. Generic language, speed and emotion fields are not used.

Advanced (`modelOptions` {"plapre":{...}}): `temperature` 0-2 (0.8), `top_k` -1-500 (50; -1 or 0 disables), `top_p` 0-1 (0.95), `silence_duration_sec` 0-10 (0.1), `text_chunk_size` 1-12000 (300).
