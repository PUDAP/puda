package puda

import (
	"os"
	"os/user"
	"strings"

	"github.com/google/uuid"
)

// fallbackUsername is used when no usable OS username is available.
const fallbackUsername = "puda-user"

// osUsername returns the raw OS account name; swapped in tests.
var osUsername = func() string {
	if u, err := user.Current(); err == nil && strings.TrimSpace(u.Username) != "" {
		return u.Username
	}
	for _, env := range []string{"USER", "USERNAME"} {
		if v := strings.TrimSpace(os.Getenv(env)); v != "" {
			return v
		}
	}
	return ""
}

// sanitizeUsername strips a Windows DOMAIN\ prefix and replaces runs of
// characters outside [A-Za-z0-9._-] with a single hyphen.
func sanitizeUsername(raw string) string {
	name := strings.TrimSpace(raw)
	if i := strings.LastIndex(name, `\`); i >= 0 {
		name = name[i+1:]
	}
	var b strings.Builder
	pendingHyphen := false
	for _, r := range name {
		if r < 0x80 && (r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '_' || r == '-') {
			if pendingHyphen && b.Len() > 0 {
				b.WriteByte('-')
			}
			pendingHyphen = false
			b.WriteRune(r)
			continue
		}
		pendingHyphen = true
	}
	if b.Len() == 0 {
		return fallbackUsername
	}
	return b.String()
}

// ensureIdentity fills a missing username or user ID. A generated username is
// marked Default so puda login can replace it while keeping the user ID.
// It reports whether the config changed.
func ensureIdentity(cfg *GlobalConfig) bool {
	changed := false
	if strings.TrimSpace(cfg.User.Username) == "" {
		cfg.User.Username = sanitizeUsername(osUsername())
		cfg.User.Default = true
		changed = true
	}
	if strings.TrimSpace(cfg.User.UserID) == "" {
		cfg.User.UserID = uuid.NewString()
		changed = true
	}
	return changed
}
