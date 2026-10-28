# XTTS v2 (xtts-v2-q8 / -q4 / -orig)

Apply with `update_work` {"id","settings":{...}}. Requires audio.cpp v0.9.3. Output is mono 24 kHz.

- Always requires `voiceId`, with 6-30 seconds of reference audio. Do not use `voiceMode` or `speaker`.
- `synthesisLanguage` is required in the request: `en`, `es`, `fr`, `de`, `it`, `pt`, `pl`, `tr`, `ru`, `nl`, `cs`, `ar`, `zh-cn`, `hu`, `ko`, `ja`, `hi`. Default is `zh-cn`; `auto` also resolves to `zh-cn` rather than guessing.
- `seed`: 0-4294967295; omit or -1 for random. Generic emotion and speed fields are not used.

Advanced (`modelOptions` {"xtts_v2":{...}}): `temperature` 0-2 (0.75), `top_k` 0-500 (50), `top_p` 0-1 (0.85), `repetition_penalty` 1-20 (10), `text_chunk_size` 1-12000 (256).
