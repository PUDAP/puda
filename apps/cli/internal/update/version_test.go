package update

import "testing"

func TestAlreadyOnRelease(t *testing.T) {
	tests := []struct {
		current string
		target  string
		want    bool
	}{
		{"v0.1.0-rc1", "v0.1.0-rc1", true},
		{"v0.0.36", "v0.0.36", true},
		{"0.0.36", "v0.0.36", true},
		{"dev", "v0.1.0-rc1", false},
		{"dev-feadf8f", "v0.1.0-rc1", false},
		{"dev-feadf8f-dirty", "v0.1.0-rc1", false},
		{"v0.0.36", "v0.1.0-rc1", false},
		{"v0.1.0", "v0.1.0-rc1", false},
		{"v0.1.0-rc1", "v0.1.0", false},
		{"dev-feadf8f-dirty", "dev-feadf8f-dirty", true},
	}
	for _, tc := range tests {
		if got := alreadyOnRelease(tc.current, tc.target); got != tc.want {
			t.Errorf("alreadyOnRelease(%q, %q)=%v want %v", tc.current, tc.target, got, tc.want)
		}
	}
}

func TestCompareSemverDevIsOlderThanRelease(t *testing.T) {
	if got := compareSemver("dev-feadf8f-dirty", "v0.1.0-rc1"); got != -1 {
		t.Fatalf("compareSemver(dev-dirty, rc1)=%d want -1", got)
	}
	if got := compareSemver("dev", "v0.0.36"); got != -1 {
		t.Fatalf("compareSemver(dev, v0.0.36)=%d want -1", got)
	}
}
