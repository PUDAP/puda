package cli

import (
	"bytes"
	"encoding/json"
	"reflect"
	"testing"
	"time"
)

func TestMachineStateOutputSingleMachineReturnsState(t *testing.T) {
	state := json.RawMessage(`{"timestamp":"2026-06-11T03:45:42Z","state":"idle","run_id":null}`)
	snapshot := machineStateSnapshot{
		Machines: map[string]machineStateResult{
			"first": {
				OK:    true,
				State: state,
			},
		},
		Count:     1,
		FetchedAt: time.Date(2026, 6, 11, 4, 20, 23, 0, time.UTC),
	}

	got := machineStateOutput(snapshot, []string{"first"})

	if !reflect.DeepEqual(got, state) {
		t.Fatalf("machineStateOutput() = %#v, want %#v", got, state)
	}
}

func TestMachineStateOutputMultipleMachinesReturnsSnapshot(t *testing.T) {
	snapshot := machineStateSnapshot{
		Machines: map[string]machineStateResult{
			"first": {
				OK:    true,
				State: json.RawMessage(`{"state":"idle"}`),
			},
			"biologic": {
				OK:    true,
				State: json.RawMessage(`{"state":"running"}`),
			},
		},
		Count:     2,
		FetchedAt: time.Date(2026, 6, 11, 4, 20, 23, 0, time.UTC),
	}

	got := machineStateOutput(snapshot, []string{"biologic", "first"})

	if !reflect.DeepEqual(got, snapshot) {
		t.Fatalf("machineStateOutput() = %#v, want snapshot", got)
	}
}

func TestMachineStateResultOmitsOfflineStatus(t *testing.T) {
	snapshot := machineStateSnapshot{
		Machines: map[string]machineStateResult{
			"biologic": {
				OK:    true,
				State: json.RawMessage(`{"state":"idle"}`),
			},
		},
		Count:     1,
		FetchedAt: time.Date(2026, 6, 11, 4, 20, 23, 0, time.UTC),
	}

	var buf bytes.Buffer
	if err := json.NewEncoder(&buf).Encode(snapshot); err != nil {
		t.Fatalf("Encode() error = %v", err)
	}

	if bytes.Contains(buf.Bytes(), []byte(`"online":false`)) {
		t.Fatalf("encoded snapshot includes offline status: %s", buf.String())
	}
}

func TestOfflineMachineIDsExcludesOnlineMachines(t *testing.T) {
	got := offlineMachineIDs(
		[]string{"first", "biologic", "xarm"},
		map[string]struct{}{
			"first": {},
			"xarm":  {},
		},
	)
	want := []string{"biologic"}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("offlineMachineIDs() = %#v, want %#v", got, want)
	}
}
