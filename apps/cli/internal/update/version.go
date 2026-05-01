package update

import (
	"strconv"
	"strings"
)

// normalizeTag returns a tag guaranteed to have a leading "v" when it looks
// like a semver version (e.g. "1.2.3" -> "v1.2.3"). Non-semver strings
// (e.g. "dev") are returned unchanged.
func normalizeTag(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return s
	}
	if strings.HasPrefix(s, "v") || strings.HasPrefix(s, "V") {
		return "v" + strings.TrimPrefix(strings.TrimPrefix(s, "v"), "V")
	}
	if len(s) > 0 && s[0] >= '0' && s[0] <= '9' {
		return "v" + s
	}
	return s
}

func displayVersion(v string) string {
	if v == "dev" || v == "" {
		return "dev"
	}
	return normalizeTag(v)
}

// compareSemver returns -1 if a<b, 0 if equal, 1 if a>b.
// Accepts "vX.Y.Z" with optional pre-release (ignored for ordering).
// Returns 0 if either side is not a parseable version.
func compareSemver(a, b string) int {
	av, aok := parseSemver(a)
	bv, bok := parseSemver(b)
	if !aok || !bok {
		return 0
	}
	for i := 0; i < 3; i++ {
		if av[i] < bv[i] {
			return -1
		}
		if av[i] > bv[i] {
			return 1
		}
	}
	return 0
}

func parseSemver(s string) ([3]int, bool) {
	var out [3]int
	s = strings.TrimPrefix(normalizeTag(s), "v")
	if s == "" {
		return out, false
	}
	if i := strings.IndexAny(s, "-+"); i >= 0 {
		s = s[:i]
	}
	parts := strings.Split(s, ".")
	if len(parts) < 1 || len(parts) > 3 {
		return out, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

func isParseableSemver(s string) bool {
	_, ok := parseSemver(s)
	return ok
}
