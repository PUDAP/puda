package nats

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

func TestSealOpenRoundTrip(t *testing.T) {
	ResetRing()
	t.Cleanup(ResetRing)
	SetRing(&Ring{Encrypt: bytes.Repeat([]byte{0x11}, 32)})
	frame, err := seal("puda.test.cmd.ping", []byte("ping"), bytes.Repeat([]byte{0x22}, 12))
	if err != nil {
		t.Fatal(err)
	}
	if frame[0] != 0xE2 || frame[1] != 0x01 {
		t.Fatalf("header = %x", frame[:2])
	}
	const golden = "e20102d449a3222222222222222222222222679e692e115222e206423c827e2d9559c83f9eda"
	if hex.EncodeToString(frame) != golden {
		t.Fatalf("frame = %x", frame)
	}
	plain, err := Open("puda.test.cmd.ping", frame)
	if err != nil {
		t.Fatal(err)
	}
	if string(plain) != "ping" {
		t.Fatalf("plain = %q", plain)
	}
	if _, err := Open("puda.test.cmd.ping", []byte("ping")); err == nil {
		t.Fatal("expected plaintext to be rejected")
	}
	flipped := append([]byte(nil), frame...)
	flipped[len(flipped)-1] ^= 0x01
	if _, err := Open("puda.test.cmd.ping", flipped); err == nil {
		t.Fatal("expected tampered frame to fail")
	}
	if _, err := Open("puda.other.cmd.ping", frame); err == nil {
		t.Fatal("expected subject mismatch to fail")
	}
}

func TestPreviousKey(t *testing.T) {
	ResetRing()
	t.Cleanup(ResetRing)
	old := bytes.Repeat([]byte{0x33}, 32)
	SetRing(&Ring{Encrypt: old})
	frame, err := seal("puda.test.cmd.ping", []byte("ping"), bytes.Repeat([]byte{0x22}, 12))
	if err != nil {
		t.Fatal(err)
	}
	SetRing(&Ring{Encrypt: bytes.Repeat([]byte{0x11}, 32), Previous: old})
	if _, err := Open("puda.test.cmd.ping", frame); err != nil {
		t.Fatal(err)
	}
	SetRing(&Ring{Encrypt: bytes.Repeat([]byte{0x11}, 32)})
	if _, err := Open("puda.test.cmd.ping", frame); err == nil {
		t.Fatal("expected old key to be rejected")
	}
}

func TestFrameWithoutKey(t *testing.T) {
	ResetRing()
	t.Cleanup(ResetRing)
	SetRing(&Ring{Encrypt: bytes.Repeat([]byte{0x11}, 32)})
	frame, err := seal("puda.test.cmd.ping", []byte("ping"), bytes.Repeat([]byte{0x22}, 12))
	if err != nil {
		t.Fatal(err)
	}
	SetRing(nil)
	if _, err := Open("puda.test.cmd.ping", frame); err == nil {
		t.Fatal("expected encryption-enabled error")
	}
	if got, err := Open("puda.test.cmd.ping", []byte("ping")); err != nil || string(got) != "ping" {
		t.Fatalf("passthrough got %q err %v", got, err)
	}
}

func TestTLSURLRequiresCA(t *testing.T) {
	ResetSession()
	t.Cleanup(ResetSession)
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("PUDA_NATS_CA", "")
	if _, err := OptionsForServers("tls://127.0.0.1:4222"); err == nil {
		t.Fatal("expected missing CA error")
	}
	if _, err := OptionsForServers("nats://127.0.0.1:4222"); err != nil {
		t.Fatal(err)
	}
}

func TestPlainProfileIgnoresDefaultKey(t *testing.T) {
	ResetSession()
	t.Cleanup(ResetSession)
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv("PUDA_E2E_KEY_FILE", "")
	writeTestKey(t, filepath.Join(dir, "puda", "e2e.key"), bytes.Repeat([]byte{0x11}, 32))

	if err := ApplyConnection(puda.Connection{ExplicitE2E: true, Servers: "nats://127.0.0.1:4222"}); err != nil {
		t.Fatal(err)
	}
	if Enabled() {
		t.Fatal("plaintext profile turned encryption on")
	}
	plain, err := Seal("puda.test.cmd.ping", []byte("ping"))
	if err != nil {
		t.Fatal(err)
	}
	if string(plain) != "ping" {
		t.Fatalf("sealed plaintext profile payload: %x", plain)
	}
}

func TestEncryptedProfileUsesItsKeyAndCA(t *testing.T) {
	ResetSession()
	t.Cleanup(ResetSession)
	dir := t.TempDir()
	envKey := filepath.Join(dir, "env.key")
	profileKey := filepath.Join(dir, "profile.key")
	ca := filepath.Join(dir, "ca.pem")
	writeTestKey(t, envKey, bytes.Repeat([]byte{0x11}, 32))
	profileKeyBytes := bytes.Repeat([]byte{0x22}, 32)
	writeTestKey(t, profileKey, profileKeyBytes)
	if err := os.WriteFile(ca, []byte("ca"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PUDA_E2E_KEY_FILE", envKey)
	t.Setenv("PUDA_NATS_CA", "")

	if err := ApplyConnection(puda.Connection{
		ExplicitE2E: true,
		E2E:         true,
		CA:          ca,
		KeyFile:     profileKey,
		Servers:     "tls://127.0.0.1:4222",
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := OptionsForServers("tls://127.0.0.1:4222"); err != nil {
		t.Fatal(err)
	}
	frame, err := Seal("puda.test.cmd.ping", []byte("ping"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(frame[2:6], kidFor(profileKeyBytes)) {
		t.Fatal("profile sealed with the environment key")
	}
}

func writeTestKey(t *testing.T, path string, key []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	body := "encrypt=" + base64.StdEncoding.EncodeToString(key) + "\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
}
