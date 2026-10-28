# Fish Audio Drama 3 (fish-drama3-small-iq3 / -q2 / -q4)

Apply with `update_work` {"id","settings":{...}}. Requires audio.cpp v0.9.3. Output is 44.1 kHz.

- `voiceMode=design` (default): packaged default voice; do not set `voiceId`.
- `voiceMode=clone`: requires `voiceId` and a nonempty `referenceText` (max 2000 chars) containing the exact full transcript.
- Text supports speaker tags `<|speaker:0|>` through `<|speaker:15|>` and event tags such as `[laughs]` and `[sighs]`. Put each tag directly in the text before the utterance or event it controls.
- `seed`: 0-2147483647; omit or -1 for random. Generic language, speed and emotion fields are not used.

Advanced (`modelOptions` {"fish_drama3":{...}}): `top_p` 0-1 (0.9), `temperature` 0-2 (1), `max_tokens` 1-16384 (1024), `text_chunk_size` 1-12000 (128). Do not enable disk/CPU expert options through work settings; they are session-level memory trade-offs, not voice controls.
