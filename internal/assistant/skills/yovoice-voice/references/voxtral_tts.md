# Voxtral 4B TTS (voxtral-tts-4b-q8 / -bf16)

Apply with `update_work` {"id","settings":{...}}. Requires audio.cpp v0.9.3. Output is mono 24 kHz.

- Built-in voices only; never set `voiceId` or `voiceMode=clone`.
- `speaker`: one of `casual_female`, `casual_male` (default), `cheerful_female`, `neutral_female`, `neutral_male`, `pt_male`, `pt_female`, `nl_male`, `nl_female`, `it_male`, `it_female`, `fr_male`, `fr_female`, `es_male`, `es_female`, `de_male`, `de_female`, `ar_male`, `hi_male`, `hi_female`.
- `seed`: 0-2147483647; omit or -1 for random. Generic emotion, speed, language and reference fields are not used.

Advanced (`modelOptions` {"voxtral_tts":{...}}): `num_inference_steps` 1-100 (7), `guidance_scale` 0-10 (1.2), `max_tokens` 1-16384 (2048), `text_chunk_size` 1-12000 (300).
