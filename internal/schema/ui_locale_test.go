package schema

import "testing"

func TestUiLocaleTraditionalPreference(t *testing.T) {
	for _, locale := range []string{"zh-CN", "zh-TW", "en"} {
		if got, err := ParseUiLocale(locale); err != nil || string(got) != locale {
			t.Fatalf("locale=%s got=%s err=%v", locale, got, err)
		}
	}
	if _, err := ParseUiLocale("unexpected"); err == nil {
		t.Fatal("accepted unknown locale")
	}
}
