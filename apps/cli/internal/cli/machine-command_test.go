package cli

import (
	"bytes"
	"errors"
	"reflect"
	"testing"
)

func TestSplitImmediateCommandTargets(t *testing.T) {
	onlineMachines := map[string]struct{}{
		"first": {},
		"third": {},
	}

	online, offline := splitImmediateCommandTargets([]string{"first", "second", "third"}, onlineMachines)

	if want := []string{"first", "third"}; !reflect.DeepEqual(online, want) {
		t.Fatalf("online = %#v, want %#v", online, want)
	}
	if want := []string{"second"}; !reflect.DeepEqual(offline, want) {
		t.Fatalf("offline = %#v, want %#v", offline, want)
	}
}

func TestWriteImmediateCommandResultSuccess(t *testing.T) {
	var buf bytes.Buffer

	writeImmediateCommandResult(&buf, "Reset", "first", nil)

	want := "first: reset command sent successfully\n"
	if got := buf.String(); got != want {
		t.Fatalf("output = %q, want %q", got, want)
	}
}

func TestWriteImmediateCommandResultFailure(t *testing.T) {
	var buf bytes.Buffer

	writeImmediateCommandResult(&buf, "Reset", "second", errors.New("offline or does not exist"))

	want := "second: reset command failed: offline or does not exist\n"
	if got := buf.String(); got != want {
		t.Fatalf("output = %q, want %q", got, want)
	}
}

func TestResolveRunIDUsesProvided(t *testing.T) {
	got := resolveRunID("custom-run-id")
	if got != "custom-run-id" {
		t.Fatalf("resolveRunID = %q, want %q", got, "custom-run-id")
	}
}

func TestResolveRunIDGeneratesUUID(t *testing.T) {
	got := resolveRunID("")
	if got == "" {
		t.Fatal("resolveRunID returned empty string")
	}
	if len(got) != 36 {
		t.Fatalf("resolveRunID = %q, want uuidv4 length 36", got)
	}
}
