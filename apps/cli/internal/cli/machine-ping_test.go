package cli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

func TestMachinePingCommandMetadata(t *testing.T) {
	if got, want := machinePingCmd.Use, "ping <machine_ids>"; got != want {
		t.Fatalf("Use=%q want=%q", got, want)
	}
	if !strings.Contains(machinePingCmd.Long, "comma-separated") {
		t.Fatalf("Long=%q", machinePingCmd.Long)
	}
	if machinePingCmd.Flags().Lookup("timeout") == nil {
		t.Fatal("ping command must expose --timeout")
	}
	if machineCmd.PersistentFlags().Lookup("human") == nil {
		t.Fatal("machine command must expose --human")
	}
}

func TestParseMachineIDsAcceptsCommaSeparatedAndMultipleArgs(t *testing.T) {
	got := parseMachineIDs([]string{"first, biologic", "third"})
	want := []string{"first", "biologic", "third"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got=%v want=%v", got, want)
	}
}

func TestWritePingResultsHuman(t *testing.T) {
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5, Description: "Liquid-handling robot."},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	writePingResults(&buf, results, nil, true)
	output := buf.String()
	for _, want := range []string{"first: pong", "status=busy", "2.500ms", "sdk=0.0.17", "Liquid-handling robot.", "offline: failed: timeout"} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
}

func TestWritePingResultsJSONIsDefault(t *testing.T) {
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5, Description: "Liquid-handling robot."},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	if err := writePingResults(&buf, results, nil, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Results   []pudanats.PingResult `json:"results"`
		Count     int                   `json:"count"`
		Responded int                   `json:"responded"`
		Failed    int                   `json:"failed"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	if payload.Count != 2 || payload.Responded != 1 || payload.Failed != 1 {
		t.Fatalf("got counts count=%d responded=%d failed=%d", payload.Count, payload.Responded, payload.Failed)
	}
	if payload.Results[0].MachineID != "first" || payload.Results[0].Description != "Liquid-handling robot." || payload.Results[1].Error != "timeout" {
		t.Fatalf("unexpected results: %+v", payload.Results)
	}
}

func TestWriteListResultsJSONIsDefault(t *testing.T) {
	pongs := []pudanats.PingResult{
		{MachineID: "biologic", Status: "pong", Description: "Potentiostat."},
		{MachineID: "first", Status: "pong"},
	}
	var buf bytes.Buffer
	if err := writeListResults(&buf, pongs, nil, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Machines []listedMachine `json:"machines"`
		Count    int             `json:"count"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	if payload.Count != 2 {
		t.Fatalf("got %+v", payload)
	}
	if payload.Machines[0].MachineID != "biologic" || payload.Machines[0].Description != "Potentiostat." || len(payload.Machines[0].Livestreams) != 0 {
		t.Fatalf("got %+v", payload.Machines[0])
	}
	if payload.Machines[1].MachineID != "first" || payload.Machines[1].Description != "" || len(payload.Machines[1].Livestreams) != 0 {
		t.Fatalf("got %+v", payload.Machines[1])
	}
}

func TestWriteListResultsHuman(t *testing.T) {
	var buf bytes.Buffer
	if err := writeListResults(&buf, []pudanats.PingResult{
		{MachineID: "first", Description: "Software-only test machine."},
	}, nil, true); err != nil {
		t.Fatal(err)
	}
	if got, want := buf.String(), "1 machines found:\n  first: Software-only test machine.\n"; got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestWriteListResultsJoinsLivestreams(t *testing.T) {
	byMachine := map[string][]pudanats.LivestreamRef{
		"first": {
			{Name: "deck", Host: "first", Description: "Deck view", URLs: pudanats.DeriveLivestreamURLs("first", "deck")},
			{Name: "room", Host: "lab", Description: "Lab overview", URLs: pudanats.DeriveLivestreamURLs("lab", "room")},
		},
	}
	pongs := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", Description: "Gantry."},
		{MachineID: "biologic", Status: "pong"},
	}
	var jsonBuf bytes.Buffer
	if err := writeListResults(&jsonBuf, pongs, byMachine, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Machines []listedMachine `json:"machines"`
	}
	if err := json.Unmarshal(jsonBuf.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Machines[0].Livestreams) != 2 || payload.Machines[0].Livestreams[0].Name != "deck" {
		t.Fatalf("first livestreams=%+v", payload.Machines[0].Livestreams)
	}
	if len(payload.Machines[1].Livestreams) != 0 {
		t.Fatalf("biologic livestreams=%+v", payload.Machines[1].Livestreams)
	}

	var humanBuf bytes.Buffer
	if err := writeListResults(&humanBuf, pongs, byMachine, true); err != nil {
		t.Fatal(err)
	}
	if got, want := humanBuf.String(), "2 machines found:\n  first: Gantry. (2 livestreams)\n  biologic\n"; got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestWritePingResultsJoinsLivestreams(t *testing.T) {
	byMachine := map[string][]pudanats.LivestreamRef{
		"first": {{Name: "deck", Host: "first", Description: "Deck view", URLs: pudanats.DeriveLivestreamURLs("first", "deck")}},
	}
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "idle", LatencyMS: 1, SDKVersion: "1.0", UptimeSeconds: 2, Description: "Gantry."},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var jsonBuf bytes.Buffer
	if err := writePingResults(&jsonBuf, results, byMachine, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Results []pingResultJSON `json:"results"`
	}
	if err := json.Unmarshal(jsonBuf.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Results[0].Livestreams) != 1 || payload.Results[0].Livestreams[0].URLs.HLS != "http://first:8888/deck/" {
		t.Fatalf("pong livestreams=%+v", payload.Results[0].Livestreams)
	}
	if payload.Results[1].Livestreams == nil || len(payload.Results[1].Livestreams) != 0 {
		t.Fatalf("failed livestreams=%v", payload.Results[1].Livestreams)
	}

	var humanBuf bytes.Buffer
	if err := writePingResults(&humanBuf, results, byMachine, true); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"first: pong", "Gantry.", "livestream deck: Deck view", "host: first", "hls: http://first:8888/deck/", "rtsp: rtsp://first:8554/deck", "offline: failed: timeout"} {
		if !strings.Contains(humanBuf.String(), want) {
			t.Fatalf("output missing %q: %s", want, humanBuf.String())
		}
	}
}
