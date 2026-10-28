# Gradium Phonon 31m English (gradium-phonon-31m-en-q8)

Apply with `update_work` {"id","settings":{...}}. Requires audio.cpp v0.9.3. Output is mono 24 kHz.

- English and the packaged default voice only. Do not set `voiceId`, `voiceMode`, or `speaker`; reference-audio cloning is unavailable.
- `synthesisLanguage`: `en` (default). Generic speed and emotion fields are not used.
- `seed`: 0-4294967295; omit or -1 for random.

Advanced (`modelOptions` {"gradium_phonon":{...}}): `temperature` 0.01-2 (0.3), `text_chunk_tokens` 1-4096 (50).
