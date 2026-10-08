package nats

import (
	"bytes"
	"encoding/hex"
	"testing"
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
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("PUDA_NATS_CA", "")
	if _, err := OptionsForServers("tls://127.0.0.1:4222"); err == nil {
		t.Fatal("expected missing CA error")
	}
	if _, err := OptionsForServers("nats://127.0.0.1:4222"); err != nil {
		t.Fatal(err)
	}
}
