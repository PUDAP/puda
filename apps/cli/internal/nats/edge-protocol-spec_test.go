package nats

// Conformance tests against the shared Edge Protocol 1.0 artifacts in
// docs/edge-protocol/v1.0. The Python SDK runs the same checks
// (libs/python-sdk/tests/test_edge_protocol_spec.py), so a change that makes
// either side drift from the spec fails a test.

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/santhosh-tekuri/jsonschema/v6"
)

var specDir = filepath.Join("..", "..", "..", "..", "docs", "edge-protocol", "v1.0")

func specFile(t *testing.T, parts ...string) []byte {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(append([]string{specDir}, parts...)...))
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func specExamples(t *testing.T, patterns ...string) []string {
	t.Helper()
	var paths []string
	for _, pattern := range patterns {
		found, err := filepath.Glob(filepath.Join(specDir, "examples", pattern))
		if err != nil {
			t.Fatal(err)
		}
		paths = append(paths, found...)
	}
	if len(paths) == 0 {
		t.Fatalf("no spec examples match %v", patterns)
	}
	return paths
}

func specSchema(t *testing.T, name string) *jsonschema.Schema {
	t.Helper()
	path, err := filepath.Abs(filepath.Join(specDir, "schemas", name+".schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	schema, err := jsonschema.NewCompiler().Compile(path)
	if err != nil {
		t.Fatal(err)
	}
	return schema
}

func validateSpec(t *testing.T, schema *jsonschema.Schema, label string, data []byte) {
	t.Helper()
	instance, err := jsonschema.UnmarshalJSON(bytes.NewReader(data))
	if err != nil {
		t.Fatalf("%s: %v", label, err)
	}
	if err := schema.Validate(instance); err != nil {
		t.Errorf("%s does not match the spec schema: %v\n%s", label, err, data)
	}
}

func jsonValue(t *testing.T, data []byte) any {
	t.Helper()
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		t.Fatal(err)
	}
	return value
}

// schemaProperties returns the property names of the schema node at path,
// following "properties" between names (e.g. "header" in nats-message).
func schemaProperties(t *testing.T, name string, path ...string) []string {
	t.Helper()
	node := jsonValue(t, specFile(t, "schemas", name+".schema.json")).(map[string]any)
	for _, key := range path {
		if props, ok := node["properties"].(map[string]any); ok && props[key] != nil {
			node = props[key].(map[string]any)
		} else {
			node = node[key].(map[string]any)
		}
	}
	var names []string
	for key := range node["properties"].(map[string]any) {
		names = append(names, key)
	}
	return names
}

// requirePreserved fails when a spec field of original is missing or changed
// after the CLI decodes and re-encodes it: a renamed JSON tag or a lossy Go type
// drops data the edge sent. Null and empty-object values (the schema default for
// params and kwargs) may be omitted.
func requirePreserved(t *testing.T, label string, original, decoded map[string]any, fields []string) {
	t.Helper()
	for _, field := range fields {
		want, ok := original[field]
		if object, isObject := want.(map[string]any); !ok || want == nil || (isObject && len(object) == 0) {
			continue
		}
		if got := decoded[field]; !reflect.DeepEqual(got, want) {
			t.Errorf("%s: field %q is %#v after the CLI decodes it, want %#v", label, field, got, want)
		}
	}
}

func TestSpecE2EVectors(t *testing.T) {
	t.Cleanup(ResetRing)
	var doc struct {
		Positive []struct {
			Name          string `json:"name"`
			Aad           string `json:"aad"`
			KeyB64        string `json:"key_b64"`
			NonceHex      string `json:"nonce_hex"`
			PlaintextUTF8 string `json:"plaintext_utf8"`
			FrameHex      string `json:"frame_hex"`
		} `json:"positive"`
		Negative []struct {
			Name     string   `json:"name"`
			Aad      string   `json:"aad"`
			FrameHex string   `json:"frame_hex"`
			KeysB64  []string `json:"keys_b64"`
			Expect   string   `json:"expect"`
		} `json:"negative"`
	}
	if err := json.Unmarshal(specFile(t, "vectors", "e2e-vectors.json"), &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Positive) == 0 || len(doc.Negative) == 0 {
		t.Fatal("spec vectors are empty")
	}
	decode := func(name string, f func(string) ([]byte, error), s string) []byte {
		out, err := f(s)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		return out
	}
	for _, v := range doc.Positive {
		key := decode(v.Name, base64.StdEncoding.DecodeString, v.KeyB64)
		nonce := decode(v.Name, hex.DecodeString, v.NonceHex)
		frame := decode(v.Name, hex.DecodeString, v.FrameHex)
		SetRing(&Ring{Encrypt: key})
		sealed, err := seal(v.Aad, []byte(v.PlaintextUTF8), nonce)
		if err != nil || !bytes.Equal(sealed, frame) {
			t.Errorf("%s: CLI seal is not byte-identical to the spec frame (err %v)", v.Name, err)
		}
		plain, err := Open(v.Aad, frame)
		if err != nil || string(plain) != v.PlaintextUTF8 {
			t.Errorf("%s: CLI cannot open the spec frame (err %v)", v.Name, err)
		}
	}
	for _, v := range doc.Negative {
		var next *Ring
		if len(v.KeysB64) > 0 {
			next = &Ring{Encrypt: decode(v.Name, base64.StdEncoding.DecodeString, v.KeysB64[0])}
			if len(v.KeysB64) > 1 {
				next.Previous = decode(v.Name, base64.StdEncoding.DecodeString, v.KeysB64[1])
			}
		}
		SetRing(next)
		data := decode(v.Name, hex.DecodeString, v.FrameHex)
		outcome := "accept"
		if plain, err := Open(v.Aad, data); err != nil {
			outcome = "reject"
		} else if next == nil && bytes.Equal(plain, data) {
			outcome = "accept_as_plaintext"
		}
		if outcome != v.Expect {
			t.Errorf("negative %s: CLI outcome %s, spec expects %s", v.Name, outcome, v.Expect)
		}
	}
}

func TestSpecEnvelopeExamplesDecode(t *testing.T) {
	schema := specSchema(t, "nats-message")
	sections := map[string][]string{}
	for _, section := range []string{"header", "command", "response"} {
		sections[section] = schemaProperties(t, "nats-message", section)
	}
	for _, path := range specExamples(t, "command-*.json", "response-*.json", "update-*.json") {
		label := filepath.Base(path)
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		var msg puda.NATSMessage
		if err := json.Unmarshal(data, &msg); err != nil {
			t.Errorf("%s: CLI cannot decode the spec example: %v", label, err)
			continue
		}
		encoded, err := json.Marshal(msg)
		if err != nil {
			t.Fatal(err)
		}
		validateSpec(t, schema, label+" re-encoded by the CLI", encoded)
		original := jsonValue(t, data).(map[string]any)
		decoded := jsonValue(t, encoded).(map[string]any)
		for section, fields := range sections {
			want, _ := original[section].(map[string]any)
			if want == nil {
				continue
			}
			got, _ := decoded[section].(map[string]any)
			requirePreserved(t, label+" "+section, want, got, fields)
		}
	}
}

func TestSpecPongExampleDecodes(t *testing.T) {
	fields := schemaProperties(t, "pong")
	// pong-error.json is not covered: the CLI only ever sends "ping", and
	// parsePong discards error pongs.
	for _, path := range specExamples(t, "pong.json") {
		label := filepath.Base(path)
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		original := jsonValue(t, data).(map[string]any)
		var pong PingResult
		if err := json.Unmarshal(data, &pong); err != nil {
			t.Fatalf("%s: %v", label, err)
		}
		encoded, err := json.Marshal(pong)
		if err != nil {
			t.Fatal(err)
		}
		requirePreserved(t, label, original, jsonValue(t, encoded).(map[string]any), fields)
		if _, ok := parsePong(data); !ok {
			t.Errorf("%s: CLI does not accept the spec pong", label)
		}
		if ClassifyProtocol(pong.ProtocolVersion) != ProtocolSupported {
			t.Errorf("%s: CLI classifies spec protocol_version %q as unsupported", label, pong.ProtocolVersion)
		}
	}
}

func TestSpecCatalogExampleDecodes(t *testing.T) {
	data := specFile(t, "examples", "machine-commands.json")
	var catalog MachineCommands
	if err := json.Unmarshal(data, &catalog); err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(catalog)
	if err != nil {
		t.Fatal(err)
	}
	validateSpec(t, specSchema(t, "machine-commands"), "machine-commands.json re-encoded by the CLI", encoded)
	original := jsonValue(t, data).(map[string]any)
	decoded := jsonValue(t, encoded).(map[string]any)
	requirePreserved(t, "machine-commands.json", original, decoded, []string{"commands", "hooks", "protocol_version"})
	entryFields := schemaProperties(t, "machine-commands", "$defs", "entry")
	wantEntries, gotEntries := original["catalog"].([]any), decoded["catalog"].([]any)
	if len(gotEntries) != len(wantEntries) {
		t.Fatalf("catalog has %d entries after decoding, want %d", len(gotEntries), len(wantEntries))
	}
	for i := range wantEntries {
		requirePreserved(t, "catalog entry", wantEntries[i].(map[string]any), gotEntries[i].(map[string]any), entryFields)
	}
}

func TestCLIPayloadsMatchSpecSchemas(t *testing.T) {
	envelope := specSchema(t, "nats-message")
	runID := "22222222-2222-4333-8444-555555555555"
	user := "00000000-0000-4000-8000-000000000001"
	for label, msg := range map[string]puda.NATSMessage{
		"queue command": BuildCommandPayload(puda.CommandRequest{
			Name: "echo", Params: map[string]interface{}{"message": "hi"}, StepNumber: 1, MachineID: "proto-test",
		}, "proto-test", runID, user, "puda"),
		"start": BuildCommandPayload(puda.CommandRequest{
			Name: puda.ImmediateCommandStart, Params: map[string]interface{}{}, MachineID: "proto-test",
		}, "proto-test", runID, user, "puda"),
		"pause": BuildCommandPayload(puda.CommandRequest{
			Name: puda.ImmediateCommandPause, Params: map[string]interface{}{}, MachineID: "proto-test",
		}, "proto-test", "", user, "puda"),
		"complete abort": BuildCommandPayload(puda.CommandRequest{
			Name: puda.ImmediateCommandComplete, Params: map[string]interface{}{"abort": true}, MachineID: "proto-test",
		}, "proto-test", runID, user, "puda"),
		"update": buildUpdateMessage("proto-test", runID, user, "puda", UpdateParams{SourceType: "git", Ref: "main"}),
	} {
		encoded, err := json.Marshal(msg)
		if err != nil {
			t.Fatal(err)
		}
		validateSpec(t, envelope, "CLI "+label, encoded)
	}
	record := mustJSON(keyringRecord{
		NewKey: encodeKey(bytes.Repeat([]byte{0x11}, 32)), OldKey: encodeKey(bytes.Repeat([]byte{0x22}, 32)),
		EncryptKID: kidHex(kidFor(bytes.Repeat([]byte{0x11}, 32))),
	})
	validateSpec(t, specSchema(t, "keyring-record"), "CLI keyring record", record)
}
