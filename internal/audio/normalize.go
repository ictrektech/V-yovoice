package audio

import (
	"math"
	"os"
)

// Normalized 是响度归一化的结果：调整前后的响度（LUFS）、调整后的真峰值（dBTP）与增益（dB）。
// Limited 表示为了不超过峰值上限，没能提到目标响度。
type Normalized struct {
	Before  float64 `json:"before"`
	After   float64 `json:"after"`
	Peak    float64 `json:"peak"`
	Gain    float64 `json:"gain"`
	Limited bool    `json:"limited,omitempty"`
}

// Normalize 把 WAV 文件就地调整到目标响度，只乘一个整体增益、不压缩动态：
// 提升后真峰值会超过 ceiling（dBTP）时只提到峰值上限为止。静音文件不做改动。
func Normalize(path string, target, ceiling float64) (Normalized, error) {
	f, p, e := openPCM(path, os.O_RDWR)
	if e != nil {
		return Normalized{}, e
	}
	defer f.Close()
	m := NewMeter(p.rate, int(p.channels))
	if e = p.scan(f, m.Write); e != nil {
		return Normalized{}, e
	}
	before, peak := m.Loudness(), m.TruePeak()
	result := Normalized{Before: before, After: before, Peak: peak}
	if before <= Silence {
		return result, nil
	}
	gain := target - before
	if peak+gain > ceiling {
		gain, result.Limited = ceiling-peak, true
	}
	if math.Abs(gain) < 0.05 {
		return result, f.Close()
	}
	scale := float32(math.Pow(10, gain/20))
	frames := 1 << 15
	raw := make([]byte, frames*p.frame())
	samples := make([]float32, frames*int(p.channels))
	for at := int64(0); at < p.size; {
		n := min(int64(len(raw)), p.size-at)
		if _, e = f.ReadAt(raw[:n], p.offset+at); e != nil {
			return Normalized{}, e
		}
		count := int(n) / int(p.bits/8)
		p.decode(raw[:n], samples[:count])
		for i := range samples[:count] {
			samples[i] *= scale
		}
		p.encode(samples[:count], raw[:n])
		if _, e = f.WriteAt(raw[:n], p.offset+at); e != nil {
			return Normalized{}, e
		}
		at += n
	}
	result.Gain, result.After, result.Peak = gain, before+gain, peak+gain
	return result, f.Close()
}
