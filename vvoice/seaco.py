"""SeACo's two ONNX graphs; preprocessing follows the MIT-licensed FunASR frontend.

Reference: modelscope/FunASR runtime/python/onnxruntime/funasr_onnx.
No weights, remote code, PyTorch, or FunASR are loaded at inference time.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class SeacoRecognizer:
    def __init__(self, files: dict[str, str], num_threads: int) -> None:
        import kaldi_native_fbank as knf
        import onnxruntime as ort

        config = json.loads(Path(files["frontend"]).read_text())
        self.frontend = config["frontend"]
        self.cmvn = np.asarray(config["cmvn"], dtype=np.float32)
        self.pred_bias = int(config.get("predictor_bias", 0))
        self.tokens = json.loads(Path(files["tokens"]).read_text())
        self.vocab = {token: index for index, token in enumerate(self.tokens)}
        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = self.frontend.get("fs", 16000)
        opts.frame_opts.window_type = self.frontend.get("window", "hamming")
        opts.frame_opts.frame_length_ms = self.frontend.get("frame_length", 25)
        opts.frame_opts.frame_shift_ms = self.frontend.get("frame_shift", 10)
        opts.frame_opts.dither = self.frontend.get("dither", 0)
        opts.frame_opts.snip_edges = True
        opts.mel_opts.num_bins = self.frontend.get("n_mels", 80)
        opts.energy_floor = 0
        self.fbank_options = opts
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = num_threads
        # Quantized MatMul uses CPU kernels consistently across AMD/ARM/Jetson.
        self.model = ort.InferenceSession(files["model"], sess_options=session_options, providers=["CPUExecutionProvider"])
        self.embedder = ort.InferenceSession(files["embedder"], sess_options=session_options, providers=["CPUExecutionProvider"])
        self.hotword_width = self.embedder.get_inputs()[0].shape[1]
        if not isinstance(self.hotword_width, int):
            raise ValueError("SeACo hotword encoder must declare its token width")

    def _features(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        import kaldi_native_fbank as knf

        if sample_rate != int(self.fbank_options.frame_opts.samp_freq):
            raise ValueError("SeACo requires 16 kHz audio")
        fbank = knf.OnlineFbank(self.fbank_options)
        fbank.accept_waveform(sample_rate, (samples.astype(np.float32) * 32768).tolist())
        count = fbank.num_frames_ready
        if not count:
            return np.empty((0, self.cmvn.shape[1]), dtype=np.float32)
        features = np.stack([fbank.get_frame(i) for i in range(count)]).astype(np.float32)
        m, n = self.frontend.get("lfr_m", 7), self.frontend.get("lfr_n", 6)
        left = (m - 1) // 2
        padded = np.pad(features, ((left, m), (0, 0)), mode="edge")
        features = np.stack([padded[i * n:i * n + m].reshape(-1) for i in range((count + n - 1) // n)])
        return ((features + self.cmvn[0]) * self.cmvn[1]).astype(np.float32)

    def _hotword_embedding(self, phrases: list[str]) -> np.ndarray:
        words = [[self.vocab.get(char, self.vocab.get("<unk>", 8403)) for char in phrase.replace(" ", "")] for phrase in phrases]
        if any(len(word) > self.hotword_width for word in words):
            raise ValueError(f"SeACo hotwords must be at most {self.hotword_width} characters each")
        words = [word for word in words if word] + [[self.vocab.get("<s>", 1)]]
        lengths = np.asarray([len(word) - 1 for word in words])
        ids = np.zeros((len(words), self.hotword_width), dtype=np.int32)
        for i, word in enumerate(words):
            ids[i, :len(word)] = word
        feeds = {self.embedder.get_inputs()[0].name: ids}
        # Some legacy exporters retain the otherwise unused length input.
        if len(self.embedder.get_inputs()) > 1:
            feeds[self.embedder.get_inputs()[1].name] = (lengths + 1).astype(np.int32)
        embedded = self.embedder.run(None, feeds)[0].transpose(1, 0, 2)
        return embedded[np.arange(len(words)), lengths][None].astype(np.float32)

    def transcribe(self, samples: np.ndarray, sample_rate: int, phrases: list[str]) -> dict:
        bias = self._hotword_embedding(phrases)
        features = self._features(samples, sample_rate)
        if not len(features):
            return {"text": "", "tokens": [], "timestamps": []}
        inputs = self.model.get_inputs()
        logits, token_num, *_ = self.model.run(None, {
            inputs[0].name: features[None],
            inputs[1].name: np.asarray([len(features)], dtype=np.int32),
            inputs[2].name: bias,
        })
        ids = logits[0].argmax(axis=-1).tolist()
        tokens = [self.tokens[index] for index in ids if index not in {0, 2}][:max(0, int(token_num[0]) - self.pred_bias)]
        # Chinese character tokens concatenate; English sentencepiece/subword
        # boundaries are retained without performing post-hoc hotword replacement.
        text = "".join(token.replace("▁", " ").replace("@@", "") for token in tokens if token not in {"<s>", "</s>", "<blank>"}).strip()
        return {"text": text, "tokens": tokens, "timestamps": [], "language": "zh"}
