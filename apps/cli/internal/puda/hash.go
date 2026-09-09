package puda

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
)

// GetProjectHash returns the SHA-256 hex digest of the file at path.
func GetProjectHash(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", fmt.Errorf("failed to open %s: %w", path, err)
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", fmt.Errorf("failed to hash %s: %w", path, err)
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
