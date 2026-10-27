# Kokoro (kokoro-82m-q8 / -bf16, kokoro-1.1-zh-q8)

A small fixed-voice model: no cloning, no description, no emotion. Apply with `update_work` {"id","settings":{...}}.

- `speaker`: one of the model's `voices` (see `list_models` → catalog entry of the work's model), or a positive-weight blend of two voices in the same language, e.g. `zf_xiaobei(0.7)+zf_xiaoni(0.3)`. The first voice determines the synthesis language. For a single voice, the first letter is the language, the second the gender: a = American English, b = British English, e = Spanish, f = French, h = Hindi, i = Italian, j = Japanese, p = Brazilian Portuguese, z = Chinese; then f/m (female/male), e.g. `af_bella`, `bm_george`, `zf_xiaoxiao`, `zm_yunxi`. Default is the first `zf_` voice. kokoro-1.1-zh uses numbered voices like `zf_001`, `zm_009`.
- `synthesisLanguage`: leave empty/`auto`, or exactly the language of the first chosen speaker (`en-us`, `en-gb`, `es`, `fr-fr`, `hi`, `it`, `ja`, `pt-br`, `zh`); a mismatch is rejected.
- `seed` 0-2147483647 (-1 = random).
- Advanced (`modelOptions` {"kokoro_tts":{...}}): `text_chunk_size` 32-120 characters per segment. It is optional and does not default to 64; Chinese and Japanese text is segmented upstream at 100 Unicode code points.
Everything else (speed, temperature, emotion, voiceId) is ignored.
