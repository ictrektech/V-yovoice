package vos

import "testing"

func TestKokoroSpeechLanguageUsesActualVoiceAccent(t *testing.T) {
	for _, row := range [][3]string{{"af_heart", "en", "en-us"}, {"bf_emma", "en", "en-gb"}, {"ff_siwis", "fr", "fr-fr"}, {"pf_dora", "pt", "pt-br"}, {"af_heart", "en-gb", "en-gb"}, {"af_heart", "zh", "zh"}, {"af_heart", "auto", "auto"}} {
		if got := kokoroSpeechLanguage(row[0], row[1]); got != row[2] {
			t.Fatalf("voice=%s language=%s got=%s", row[0], row[1], got)
		}
	}
}
