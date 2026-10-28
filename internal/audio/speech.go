package audio

import (
	"math"
)

// Span 是一段音频的起止时间（秒）。
type Span struct {
	Start float64 `json:"start"`
	End   float64 `json:"end"`
}

// 参考音频最好是 5–15 秒连续、清晰、无削波的人声；越接近 10 秒越好。
const (
	referenceShortest = 5.0
	referenceLongest  = 15.0
	referenceIdeal    = 10.0
)

// PickSpeech 从一段录音里挑出最适合做参考音频的片段：人声占比高、信噪比高、没有削波和长停顿，
// 起止尽量落在句间停顿上，不切断字。录音本身不长于最长片段时返回整段。
func PickSpeech(mono []float32, rate int) Span {
	duration := float64(len(mono)) / float64(rate)
	if duration <= referenceLongest {
		return Span{0, duration}
	}
	levels := frames(mono, rate)
	mask, _, _ := voiced(levels)
	clipped := make([]int, len(levels)+1) // 削波帧数的前缀和
	voicedSum := make([]int, len(levels)+1)
	size := max(1, int(float64(rate)*frameSeconds))
	for i := range levels {
		hit := 0
		for _, v := range mono[i*size : min(len(mono), (i+1)*size)] {
			if math.Abs(float64(v)) >= 0.999 {
				hit = 1
				break
			}
		}
		clipped[i+1] = clipped[i] + hit
		voicedSum[i+1] = voicedSum[i]
		if mask[i] {
			voicedSum[i+1]++
		}
	}
	score := func(a, b int) float64 {
		length := float64(b-a) * frameSeconds
		coverage := float64(voicedSum[b]-voicedSum[a]) / float64(b-a)
		var speech []float64
		pauses, run := 0, 0
		for i := a; i < b; i++ {
			if mask[i] {
				speech = append(speech, levels[i])
				run = 0
				continue
			}
			// 片段中间 0.8 秒以上的停顿会让克隆出的语气断断续续。
			if run++; run == 40 {
				pauses++
			}
		}
		// 清晰度看片段自己的底噪：一直有噪声的片段“有声帧”很多，但人声比底噪高不了多少。
		clarity := max(0, min(1, (percentile(speech, 0.5)-percentile(levels[a:b], 0.1))/30))
		s := 0.6*min(1, coverage/0.7) + clarity - 0.2*float64(pauses) - 0.3*math.Abs(length-referenceIdeal)/referenceIdeal
		if clipped[b] > clipped[a] {
			s -= 0.5
		}
		return s
	}
	// 候选切点：停顿开始后 0.1 秒处可作结尾，停顿结束前 0.1 秒处可作开头；只认 0.15 秒以上的停顿。
	starts, ends := []int{}, []int{}
	if mask[0] {
		starts = append(starts, 0)
	}
	for i := 0; i < len(mask); {
		if mask[i] {
			i++
			continue
		}
		j := i
		for j < len(mask) && !mask[j] {
			j++
		}
		if j-i >= 8 || i == 0 || j == len(mask) {
			ends = append(ends, min(j, i+5))
			starts = append(starts, max(i, j-5))
		}
		i = j
	}
	if mask[len(mask)-1] {
		ends = append(ends, len(mask))
	}
	shortest, longest := int(referenceShortest/frameSeconds), int(referenceLongest/frameSeconds)
	best, bestScore := Span{}, math.Inf(-1)
	for _, a := range starts {
		for _, b := range ends {
			if b-a < shortest || b-a > longest {
				continue
			}
			if s := score(a, b); s > bestScore {
				best, bestScore = Span{float64(a) * frameSeconds, float64(b) * frameSeconds}, s
			}
		}
	}
	if bestScore > math.Inf(-1) {
		best.End = min(best.End, duration)
		return best
	}
	// 一直在说、找不到合适的停顿：按固定长度每 0.5 秒滑动一次挑最好的。
	for a := 0; a+longest <= len(levels); a += 25 {
		if s := score(a, a+longest); s > bestScore {
			best, bestScore = Span{float64(a) * frameSeconds, float64(a+longest) * frameSeconds}, s
		}
	}
	best.End = min(best.End, duration)
	return best
}
