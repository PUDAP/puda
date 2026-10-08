package nats

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	natsio "github.com/nats-io/nats.go"
)

const (
	e2eMagic       = 0xE2
	e2eVersion     = 0x01
	e2eHeaderLen   = 18
	e2eTagLen      = 16
	e2eKeyLen      = 32
	keyringBucket  = "E2E_KEYRING"
	keyringKey     = "current"
	keyfilesBucket = "E2E_KEYFILES"
)

// Ring is the lab key that seals new messages, plus at most one other key.
type Ring struct {
	Encrypt    []byte
	Previous   []byte
	Persistent bool
	Path       string
}

var (
	ringMu   sync.RWMutex
	ring     *Ring
	ringLoad bool
)

func kidFor(key []byte) []byte {
	sum := sha256.Sum256(key)
	return sum[:4]
}

func kidHex(keyID []byte) string {
	return hex.EncodeToString(keyID)
}

func kvAAD(bucket, key string) string {
	return "kv:" + bucket + ":" + key
}

func (r *Ring) encryptKID() []byte {
	return kidFor(r.Encrypt)
}

func (r *Ring) decryptKIDs() [][]byte {
	kids := [][]byte{r.encryptKID()}
	if len(r.Previous) == e2eKeyLen {
		kids = append(kids, kidFor(r.Previous))
	}
	return kids
}

func (r *Ring) keyFor(keyID []byte) ([]byte, error) {
	if bytesEqual(keyID, r.encryptKID()) {
		return r.Encrypt, nil
	}
	if len(r.Previous) == e2eKeyLen && bytesEqual(keyID, kidFor(r.Previous)) {
		return r.Previous, nil
	}
	return nil, fmt.Errorf("unknown key id")
}

// Enabled reports whether a lab key is configured.
func Enabled() bool {
	return loadRing() != nil
}

func loadRing() *Ring {
	ringMu.RLock()
	if ringLoad {
		defer ringMu.RUnlock()
		return ring
	}
	ringMu.RUnlock()
	ringMu.Lock()
	defer ringMu.Unlock()
	if !ringLoad {
		loaded, err := readRing()
		if err != nil {
			ring = nil
		} else {
			ring = loaded
		}
		ringLoad = true
	}
	return ring
}

// ReloadRing reads the lab key again.
func ReloadRing() (*Ring, error) {
	loaded, err := readRing()
	ringMu.Lock()
	defer ringMu.Unlock()
	ringLoad = true
	if err != nil {
		ring = nil
		return nil, err
	}
	ring = loaded
	return ring, nil
}

// SetRing installs a ring for this process. Tests use it.
func SetRing(next *Ring) {
	ringMu.Lock()
	defer ringMu.Unlock()
	ring = next
	ringLoad = true
}

// ResetRing clears the cached ring so the next call reads the environment.
func ResetRing() {
	ringMu.Lock()
	defer ringMu.Unlock()
	ring = nil
	ringLoad = false
}

// Seal frames plaintext when a lab key is set and returns it unchanged otherwise.
func Seal(subject string, plaintext []byte) ([]byte, error) {
	return seal(subject, plaintext, nil)
}

func seal(subject string, plaintext, nonce []byte) ([]byte, error) {
	current := loadRing()
	if current == nil {
		return plaintext, nil
	}
	if nonce == nil {
		nonce = make([]byte, 12)
		if _, err := rand.Read(nonce); err != nil {
			return nil, fmt.Errorf("failed to generate nonce: %w", err)
		}
	}
	if len(nonce) != 12 {
		return nil, fmt.Errorf("nonce must be 12 bytes")
	}
	keyID := current.encryptKID()
	block, err := aes.NewCipher(current.Encrypt)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	ciphertext := aead.Seal(nil, nonce, plaintext, []byte(subject))
	frame := make([]byte, 0, e2eHeaderLen+len(ciphertext))
	frame = append(frame, e2eMagic, e2eVersion)
	frame = append(frame, keyID...)
	frame = append(frame, nonce...)
	frame = append(frame, ciphertext...)
	return frame, nil
}

// Open returns the plaintext payload. A sealed frame with no local key is an error.
func Open(subject string, data []byte) ([]byte, error) {
	framed := isFrame(data)
	current := loadRing()
	if current == nil {
		if framed {
			return nil, fmt.Errorf("peer has encryption enabled")
		}
		return data, nil
	}
	if !framed {
		return nil, fmt.Errorf("plaintext payload rejected while encryption is enabled")
	}
	key, err := current.keyFor(data[2:6])
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
	plain, err := aead.Open(nil, data[6:18], data[e2eHeaderLen:], []byte(subject))
	if err != nil {
		return nil, fmt.Errorf("failed to open payload")
	}
	return plain, nil
}

// SealKV and OpenKV use the KV bucket and key as authenticated data.
func SealKV(bucket, key string, plaintext []byte) ([]byte, error) {
	return Seal(kvAAD(bucket, key), plaintext)
}

func OpenKV(bucket, key string, data []byte) ([]byte, error) {
	return Open(kvAAD(bucket, key), data)
}

// OptionsForServers returns connect options for the given comma-separated URLs.
func OptionsForServers(servers string, extra ...natsio.Option) ([]natsio.Option, error) {
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
	opts := append([]natsio.Option{}, extra...)
	if !tlsURL {
		return opts, nil
	}
	ca := strings.TrimSpace(os.Getenv("PUDA_NATS_CA"))
	if ca == "" {
		return nil, fmt.Errorf("PUDA_NATS_CA is not set; a tls:// NATS URL needs the path to the server CA file (ca.pem)")
	}
	opts = append(opts, natsio.RootCAs(ca))
	return opts, nil
}

func isFrame(data []byte) bool {
	return len(data) >= e2eHeaderLen+e2eTagLen && data[0] == e2eMagic && data[1] == e2eVersion
}

func readRing() (*Ring, error) {
	path := configuredKeyPath()
	if path == "" {
		path = defaultKeyFileIfExists()
	}
	var fileEncrypt, filePrevious []byte
	persistent := false
	if path != "" {
		if st, err := os.Stat(path); err == nil && !st.IsDir() {
			persistent = true
			var err error
			fileEncrypt, filePrevious, err = readKeyFile(path)
			if err != nil {
				return nil, err
			}
		}
	}
	if fileEncrypt == nil {
		return nil, nil
	}
	return &Ring{Encrypt: fileEncrypt, Previous: filePrevious, Persistent: persistent, Path: path}, nil
}

func configuredKeyPath() string {
	return strings.TrimSpace(os.Getenv("PUDA_E2E_KEY_FILE"))
}

func defaultKeyFile() string {
	base, err := os.UserConfigDir()
	if err != nil {
		return ""
	}
	return filepath.Join(base, "puda", "e2e.key")
}

func defaultKeyFileIfExists() string {
	path := defaultKeyFile()
	if path == "" {
		return ""
	}
	if st, err := os.Stat(path); err == nil && !st.IsDir() {
		return path
	}
	return ""
}

func writeKeyPath() string {
	if path := configuredKeyPath(); path != "" {
		return path
	}
	return defaultKeyFile()
}

func decodeKey(value string) ([]byte, error) {
	text := strings.TrimSpace(value)
	key, err := base64.StdEncoding.DecodeString(text)
	if err != nil {
		key, err = base64.RawStdEncoding.DecodeString(text)
	}
	if err != nil || len(key) != e2eKeyLen {
		return nil, fmt.Errorf("lab key must be 32 bytes")
	}
	return key, nil
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

func writeKeyFile(path string, next *Ring) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	var b strings.Builder
	fmt.Fprintf(&b, "encrypt=%s\n", base64.StdEncoding.EncodeToString(next.Encrypt))
	if len(next.Previous) == e2eKeyLen {
		fmt.Fprintf(&b, "previous=%s\n", base64.StdEncoding.EncodeToString(next.Previous))
	}
	if err := os.WriteFile(path, []byte(b.String()), 0o600); err != nil {
		return err
	}
	idPath := path + ".id"
	if _, err := os.Stat(idPath); os.IsNotExist(err) {
		id := make([]byte, 16)
		if _, err := rand.Read(id); err != nil {
			return err
		}
		if err := os.WriteFile(idPath, []byte(hex.EncodeToString(id)+"\n"), 0o600); err != nil {
			return err
		}
	}
	return nil
}

func keyFileID(path string) (string, error) {
	data, err := os.ReadFile(path + ".id")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(data)), nil
}

func bytesEqual(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
