// Package e2e seals loadgen payloads with the same frame as the CLI.
// Keep the frame layout in sync with apps/cli/internal/nats/e2e.go.
package e2e

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"os"
	"strings"
	"sync"

	"github.com/nats-io/nats.go"
)

const (
	magic     = 0xE2
	version   = 0x01
	headerLen = 18
	tagLen    = 16
	keyLen    = 32
)

type ring struct {
	encrypt  []byte
	previous []byte
}

var (
	mu      sync.RWMutex
	current *ring
	loaded  bool
)

// Enabled reports whether a lab key is configured.
func Enabled() bool {
	return load() != nil
}

// Seal frames plaintext when a lab key is set.
func Seal(subject string, plaintext []byte) ([]byte, error) {
	keys := load()
	if keys == nil {
		return plaintext, nil
	}
	nonce := make([]byte, 12)
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}
	sum := sha256.Sum256(keys.encrypt)
	block, err := aes.NewCipher(keys.encrypt)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	ciphertext := aead.Seal(nil, nonce, plaintext, []byte(subject))
	frame := make([]byte, 0, headerLen+len(ciphertext))
	frame = append(frame, magic, version)
	frame = append(frame, sum[:4]...)
	frame = append(frame, nonce...)
	frame = append(frame, ciphertext...)
	return frame, nil
}

// Open returns plaintext. A sealed frame with no local key is an error.
func Open(subject string, data []byte) ([]byte, error) {
	framed := len(data) >= headerLen+tagLen && data[0] == magic && data[1] == version
	keys := load()
	if keys == nil {
		if framed {
			return nil, fmt.Errorf("peer has encryption enabled")
		}
		return data, nil
	}
	if !framed {
		return nil, fmt.Errorf("plaintext payload rejected while encryption is enabled")
	}
	key, err := keyFor(keys, data[2:6])
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	plain, err := aead.Open(nil, data[6:18], data[headerLen:], []byte(subject))
	if err != nil {
		return nil, fmt.Errorf("failed to open payload")
	}
	return plain, nil
}

// OptionsForServers adds the CA when every URL uses tls://.
func OptionsForServers(servers string, extra ...nats.Option) ([]nats.Option, error) {
	tlsURL := false
	plainURL := false
	for _, server := range strings.Split(servers, ",") {
		server = strings.TrimSpace(server)
		if server == "" {
			continue
		}
		switch {
		case strings.HasPrefix(server, "tls://"):
			tlsURL = true
		case strings.HasPrefix(server, "nats://"):
			plainURL = true
		default:
			return nil, fmt.Errorf("unsupported NATS URL %s", server)
		}
	}
	if tlsURL && plainURL {
		return nil, fmt.Errorf("NATS server URLs must all use tls:// or all use nats://")
	}
	opts := append([]nats.Option{}, extra...)
	if !tlsURL {
		return opts, nil
	}
	ca := strings.TrimSpace(os.Getenv("PUDA_NATS_CA"))
	if ca == "" {
		return nil, fmt.Errorf("PUDA_NATS_CA is not set; a tls:// NATS URL needs the path to the server CA file (ca.pem)")
	}
	return append(opts, nats.RootCAs(ca)), nil
}

func keyFor(keys *ring, keyID []byte) ([]byte, error) {
	sum := sha256.Sum256(keys.encrypt)
	if bytesEqual(keyID, sum[:4]) {
		return keys.encrypt, nil
	}
	if len(keys.previous) == keyLen {
		prev := sha256.Sum256(keys.previous)
		if bytesEqual(keyID, prev[:4]) {
			return keys.previous, nil
		}
	}
	return nil, fmt.Errorf("unknown key id")
}

func load() *ring {
	mu.RLock()
	if loaded {
		defer mu.RUnlock()
		return current
	}
	mu.RUnlock()
	mu.Lock()
	defer mu.Unlock()
	if loaded {
		return current
	}
	loaded = true
	encrypt, _ := envOrFile()
	current = encrypt
	return current
}

func envOrFile() (*ring, error) {
	path := strings.TrimSpace(os.Getenv("PUDA_E2E_KEY_FILE"))
	if path == "" {
		return nil, nil
	}
	encrypt, previous, err := readKeyFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	if encrypt == nil {
		return nil, nil
	}
	return &ring{encrypt: encrypt, previous: previous}, nil
}

func readKeyFile(path string) ([]byte, []byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, err
	}
	var encrypt, previous []byte
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		field, value, _ := strings.Cut(line, "=")
		switch field {
		case "encrypt":
			encrypt, err = decodeKey(value)
		case "previous":
			if strings.TrimSpace(value) != "" {
				previous, err = decodeKey(value)
			}
		}
		if err != nil {
			return nil, nil, err
		}
	}
	return encrypt, previous, nil
}

func decodeKey(value string) ([]byte, error) {
	text := strings.TrimSpace(value)
	key, err := base64.StdEncoding.DecodeString(text)
	if err != nil {
		key, err = base64.RawStdEncoding.DecodeString(text)
	}
	if err != nil || len(key) != keyLen {
		return nil, fmt.Errorf("lab key must be 32 bytes")
	}
	return key, nil
}

func bytesEqual(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	var diff byte
	for i := range a {
		diff |= a[i] ^ b[i]
	}
	return diff == 0
}
