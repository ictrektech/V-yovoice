package audio

import (
	"math"
	"slices"
	"yovoice/internal/schema"
)

// 生成结果的体检：只做测量，不用模型。阈值偏保守，宁可漏报也不让正常的录音满屏警告。

const frameSeconds = 0.02

// frames 返回单声道按 20 ms 分帧的 RMS 电平（dBFS）。
func frames(mono []float32, rate int) []float64 {
	size := max(1, int(float64(rate)*frameSeconds))
	out := make([]float64, 0, len(mono)/size+1)
	for at := 0; at < len(mono); at += size {
		sum := 0.0
		chunk := mono[at:min(len(mono), at+size)]
		for _, v := range chunk {
			sum += float64(v) * float64(v)
		}
		out = append(out, decibels(math.Sqrt(sum/float64(len(chunk)))))
	}
	return out
}

func percentile(values []float64, p float64) float64 {
	if len(values) == 0 {
		return Silence
	}
	sorted := slices.Clone(values)
	slices.Sort(sorted)
	return sorted[min(len(sorted)-1, int(p*float64(len(sorted))))]
}

// voiced 按底噪与最响部分自适应地标出有声帧，返回标记、底噪与有声阈值。
func voiced(levels []float64) (mask []bool, floor, threshold float64) {
	floor = percentile(levels, 0.1)
	loud := percentile(levels, 0.95)
	threshold = max(floor+12, loud-40, -55)
	mask = make([]bool, len(levels))
	for i, v := range levels {
		mask[i] = v > threshold
	}
	return mask, floor, threshold
}

// Inspect 测量 WAV 的响度与真峰值并找出常见问题。speech 为人声（语音、配音）时还检查截断、长静音与咔哒声；
// 音乐的前奏、间奏和收尾本来就可能很安静，只查削波、无声、过小和直流偏移。
func Inspect(path string, speech bool) (schema.AudioCheck, error) {
	channels, rate, e := Read(path)
	if e != nil {
		return schema.AudioCheck{}, e
	}
	m := NewMeter(rate, len(channels))
	block := make([]float32, 0, 4096*len(channels))
	for i := range channels[0] {
		for _, c := range channels {
			block = append(block, c[i])
		}
		if len(block) == cap(block) {
			m.Write(block)
			block = block[:0]
		}
	}
	m.Write(block)
	check := schema.AudioCheck{Loudness: round1(m.Loudness()), Peak: round1(m.TruePeak())}
	mono := mix(channels)
	duration := float64(len(mono)) / float64(rate)
	levels := frames(mono, rate)
	add := func(issue schema.AudioIssue) {
		issue.At, issue.End = round2(issue.At), round2(issue.End)
		check.Issues = append(check.Issues, issue)
	}
	if percentile(levels, 0.95) < -50 {
		add(schema.AudioIssue{Code: "silent"})
		return check, nil
	}
	if quiet := -36.0; !speech && check.Loudness < quiet-4 || speech && check.Loudness < quiet {
		add(schema.AudioIssue{Code: "quiet"})
	}
	if at, count := clipping(channels, rate); count > 0 {
		add(schema.AudioIssue{Code: "clipping", At: at, Count: count})
	}
	if mean := average(mono); math.Abs(mean) > 0.02 {
		add(schema.AudioIssue{Code: "dc"})
	}
	if !speech {
		return check, nil
	}
	if at, count := clicks(mono, rate); count > 0 {
		add(schema.AudioIssue{Code: "clicks", At: at, Count: count})
	}
	mask, _, _ := voiced(levels)
	var speechLevels []float64
	for i, v := range levels {
		if mask[i] {
			speechLevels = append(speechLevels, v)
		}
	}
	// 结尾最后 20 ms 仍接近正常说话的音量：句子被硬切断。
	if n := len(levels); n > 5 && mask[n-1] && levels[n-1] > percentile(speechLevels, 0.5)-12 {
		add(schema.AudioIssue{Code: "cutoff", At: duration})
	}
	// 2 秒以上的静音段（开头、句间或结尾），最多报告 3 处。
	reported := 0
	for i := 0; i < len(mask) && reported < 3; {
		if mask[i] {
			i++
			continue
		}
		j := i
		for j < len(mask) && !mask[j] {
			j++
		}
		if float64(j-i)*frameSeconds >= 2 {
			add(schema.AudioIssue{Code: "silence", At: float64(i) * frameSeconds, End: min(duration, float64(j)*frameSeconds)})
			reported++
		}
		i = j
	}
	return check, nil
}

// clipping 统计削波：连续 3 个以上采样贴住满幅，或浮点采样超过满幅。返回第一处的时间与次数。
func clipping(channels [][]float32, rate int) (float64, int) {
	first, count := -1, 0
	for _, c := range channels {
		run := 0
		for i, v := range c {
			a := math.Abs(float64(v))
			if a > 1.0001 {
				if run < 3 {
					count++
					if first < 0 || i < first {
						first = i
					}
				}
				run = 3
				continue
			}
			if a >= 0.999 {
				if run++; run == 3 {
					count++
					if first < 0 || i-2 < first {
						first = i - 2
					}
				}
				continue
			}
			run = 0
		}
	}
	if count == 0 {
		return 0, 0
	}
	return float64(first) / float64(rate), count
}

// clicks 找孤立的咔哒声：1 ms 内二阶差分陡增到周围 50 ms 中位数的 10 倍以上，且前后 2 ms 之外很快回落。
// 爆破音、擦音的起点会持续十几毫秒以上，不会被当成咔哒声。
func clicks(mono []float32, rate int) (float64, int) {
	size := max(1, rate/1000)
	var spikes []float64
	for at := 0; at < len(mono); at += size {
		peak := 0.0
		for i := max(2, at); i < min(len(mono), at+size); i++ {
			peak = max(peak, math.Abs(float64(mono[i]-2*mono[i-1]+mono[i-2])))
		}
		spikes = append(spikes, peak)
	}
	first, count := 0.0, 0
	around := make([]float64, 0, 50)
	for i, v := range spikes {
		if v < 0.15 {
			continue
		}
		around = around[:0]
		for j := max(0, i-25); j < min(len(spikes), i+26); j++ {
			if j < i-2 || j > i+2 {
				around = append(around, spikes[j])
			}
		}
		if len(around) < 10 {
			continue
		}
		// 静音段里的咔哒声同样刺耳：参考值给个下限，不因周围全是 0 而失效。
		reference := max(0.01, percentile(around, 0.5))
		if v < 10*reference {
			continue
		}
		isolated := true
		for _, j := range []int{i - 3, i - 2, i + 2, i + 3} {
			if j >= 0 && j < len(spikes) && spikes[j] > 3*reference {
				isolated = false
			}
		}
		if !isolated || i > 0 && spikes[i-1] >= v {
			continue
		}
		if count == 0 {
			first = float64(i*size) / float64(rate)
		}
		count++
	}
	return first, count
}

func average(mono []float32) float64 {
	sum := 0.0
	for _, v := range mono {
		sum += float64(v)
	}
	return sum / float64(max(1, len(mono)))
}

func round1(v float64) float64 { return math.Round(v*10) / 10 }
func round2(v float64) float64 { return math.Round(v*100) / 100 }
