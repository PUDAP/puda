package fleet

import (
	"fmt"
	"strings"
	"unicode"
)

func IDs(prefix string, start, count int) []string {
	prefix = sanitize(prefix)
	ids := make([]string, count)
	for i := range ids {
		ids[i] = fmt.Sprintf("%s-%d", prefix, start+i)
	}
	return ids
}

func sanitize(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	var b strings.Builder
	lastDash := false
	for _, r := range value {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(r)
			lastDash = false
		} else if !lastDash && b.Len() > 0 {
			b.WriteByte('-')
			lastDash = true
		}
	}
	return strings.Trim(b.String(), "-")
}
