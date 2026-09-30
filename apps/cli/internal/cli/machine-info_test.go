package cli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

func TestMachineListCommandMetadata(t *testing.T) {
	if got, want := machineListCmd.Use, "list"; got != want {
		t.Fatalf("Use=%q want=%q", got, want)
	}
	for _, want := range []string{
		"livestream_count",
		"registered with PUDA",
		"Other cameras may exist",
		"puda livestream list --machines",
	} {
		if !strings.Contains(machineListCmd.Long, want) {
			t.Fatalf("Long missing %q: %s", want, machineListCmd.Long)
		}
	}
	if machineListCmd.Flags().Lookup("timeout") == nil {
		t.Fatal("list command must expose --timeout")
	}
}

func TestMachineInfoCommandMetadata(t *testing.T) {
	if got, want := machineInfoCmd.Use, "info <machine_ids>"; got != want {
		t.Fatalf("Use=%q want=%q", got, want)
	}
	if !strings.Contains(machineInfoCmd.Long, "comma-separated") || !strings.Contains(machineInfoCmd.Long, "tlm_streams") {
		t.Fatalf("Long=%q", machineInfoCmd.Long)
	}
	if machineInfoCmd.Flags().Lookup("timeout") == nil {
		t.Fatal("info command must expose --timeout")
	}
	found, _, err := machineCmd.Find([]string{"ping"})
	if err != nil || found != machineInfoCmd {
		t.Fatalf("ping must alias info: found=%v err=%v", found, err)
	}
	if machineCmd.PersistentFlags().Lookup("human") == nil {
		t.Fatal("machine command must expose --human")
	}
	if machineCmd.PersistentFlags().Lookup("yes") == nil {
		t.Fatal("machine command must expose --yes")
	}
}

func TestParseMachineIDsAcceptsCommaSeparatedAndMultipleArgs(t *testing.T) {
	got := parseMachineIDs([]string{"first, biologic", "third"})
	want := []string{"first", "biologic", "third"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got=%v want=%v", got, want)
	}
}

func TestWriteInfoResultsHuman(t *testing.T) {
	results := []pudanats.PingResult{
		{
			MachineID:     "first",
			Status:        "pong",
			RunStatus:     "busy",
			LatencyMS:     2.5,
			SDKVersion:    "0.0.17",
			UptimeSeconds: 12.5,
			Description:   "Liquid-handling robot.",
			LocalIP:       "192.168.1.10",
			TailscaleIP:   "100.99.243.61",
			MagicDNS:      "host.tailnet.ts.net",
		},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	writeInfoResults(&buf, results, nil, true)
	output := buf.String()
	for _, want := range []string{
		"first: pong",
		"status=busy",
		"2.500ms",
		"sdk=0.0.17",
		"Liquid-handling robot.",
		"local_ip=192.168.1.10",
		"tailscale_ip=100.99.243.61",
		"magicdns=host.tailnet.ts.net",
		"offline: failed: timeout",
	} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
}

func TestWriteInfoResultsJSONIsDefault(t *testing.T) {
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5, Description: "Liquid-handling robot."},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	if err := writeInfoResults(&buf, results, nil, false); err != nil {
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

func TestWriteInfoResultsJSONIncludesHostAddresses(t *testing.T) {
	results := []pudanats.PingResult{
		{
			MachineID:   "first",
			Status:      "pong",
			LocalIP:     "192.168.1.10",
			TailscaleIP: "100.99.243.61",
			MagicDNS:    "host.tailnet.ts.net",
		},
	}
	var buf bytes.Buffer
	if err := writeInfoResults(&buf, results, nil, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Results []infoResultJSON `json:"results"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	got := payload.Results[0]
	if got.LocalIP != "192.168.1.10" || got.TailscaleIP != "100.99.243.61" || got.MagicDNS != "host.tailnet.ts.net" {
		t.Fatalf("got %+v", got)
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
	if payload.Machines[0].MachineID != "biologic" || payload.Machines[0].Description != "Potentiostat." || payload.Machines[0].LivestreamCount != 0 {
		t.Fatalf("got %+v", payload.Machines[0])
	}
	if payload.Machines[1].MachineID != "first" || payload.Machines[1].Description != "" || payload.Machines[1].LivestreamCount != 0 {
		t.Fatalf("got %+v", payload.Machines[1])
	}
}

func TestWriteListResultsJSONIncludesHostAddresses(t *testing.T) {
	pongs := []pudanats.PingResult{
		{
			MachineID:   "first",
			Status:      "pong",
			Description: "Software-only test machine.",
			LocalIP:     "192.168.1.10",
			TailscaleIP: "100.99.243.61",
			MagicDNS:    "host.tailnet.ts.net",
		},
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
	want := listedMachine{
		MachineID:   "first",
		Description: "Software-only test machine.",
		LocalIP:     "192.168.1.10",
		TailscaleIP: "100.99.243.61",
		MagicDNS:    "host.tailnet.ts.net",
	}
	if payload.Count != 1 || payload.Machines[0] != want {
		t.Fatalf("got %+v", payload)
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

func TestWriteInfoResultsIncludesTlmStreams(t *testing.T) {
	interval := 0.25
	results := []pudanats.PingResult{
		{
			MachineID: "balance",
			Status:    "pong",
			TlmStreams: []pudanats.TlmStream{
				{Name: "weight", Subject: "puda.balance.tlm.stream.weight", Interval: &interval, Description: "Mass in grams"},
				{Name: "ctrl", Subject: "puda.balance.tlm.stream.ctrl"},
			},
		},
		{MachineID: "old", Status: "pong"},
	}
	var jsonBuf bytes.Buffer
	if err := writeInfoResults(&jsonBuf, results, nil, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Results []infoResultJSON `json:"results"`
	}
	if err := json.Unmarshal(jsonBuf.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	got := payload.Results[0].TlmStreams
	if len(got) != 2 || got[0].Name != "weight" || got[0].Interval == nil || *got[0].Interval != 0.25 || got[1].Interval != nil {
		t.Fatalf("tlm_streams=%+v", got)
	}
	if payload.Results[1].TlmStreams == nil || len(payload.Results[1].TlmStreams) != 0 {
		t.Fatalf("old edge tlm_streams=%v", payload.Results[1].TlmStreams)
	}

	var humanBuf bytes.Buffer
	if err := writeInfoResults(&humanBuf, results, nil, true); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"tlm_stream weight every 0.25s: Mass in grams",
		"subject: puda.balance.tlm.stream.weight",
		"tlm_stream ctrl (no fixed interval)",
	} {
		if !strings.Contains(humanBuf.String(), want) {
			t.Fatalf("output missing %q: %s", want, humanBuf.String())
		}
	}
}

func TestWriteListResultsTlmStreamCount(t *testing.T) {
	pongs := []pudanats.PingResult{
		{MachineID: "balance", Status: "pong", TlmStreams: []pudanats.TlmStream{{Name: "weight"}}},
		{MachineID: "first", Status: "pong"},
	}
	var jsonBuf bytes.Buffer
	if err := writeListResults(&jsonBuf, pongs, nil, false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(jsonBuf.String(), `"tlm_stream_count": 1`) || !strings.Contains(jsonBuf.String(), `"tlm_stream_count": 0`) {
		t.Fatalf("list JSON must include tlm_stream_count for every machine:\n%s", jsonBuf.String())
	}
	var humanBuf bytes.Buffer
	if err := writeListResults(&humanBuf, pongs, nil, true); err != nil {
		t.Fatal(err)
	}
	if got, want := humanBuf.String(), "2 machines found:\n  balance (1 tlm stream)\n  first\n"; got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestWriteListResultsLivestreamCount(t *testing.T) {
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
	if payload.Machines[0].LivestreamCount != 2 {
		t.Fatalf("first livestream_count=%d", payload.Machines[0].LivestreamCount)
	}
	if payload.Machines[1].LivestreamCount != 0 {
		t.Fatalf("biologic livestream_count=%d", payload.Machines[1].LivestreamCount)
	}
	if strings.Contains(jsonBuf.String(), `"livestreams"`) || strings.Contains(jsonBuf.String(), `"urls"`) {
		t.Fatalf("list JSON must not join livestream objects:\n%s", jsonBuf.String())
	}
	if !strings.Contains(jsonBuf.String(), `"livestream_count": 2`) || !strings.Contains(jsonBuf.String(), `"livestream_count": 0`) {
		t.Fatalf("list JSON must include livestream_count for every machine:\n%s", jsonBuf.String())
	}

	var humanBuf bytes.Buffer
	if err := writeListResults(&humanBuf, pongs, byMachine, true); err != nil {
		t.Fatal(err)
	}
	if got, want := humanBuf.String(), "2 machines found:\n  first: Gantry. (2 registered livestreams)\n  biologic\n"; got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestWriteInfoResultsJoinsLivestreams(t *testing.T) {
	byMachine := map[string][]pudanats.LivestreamRef{
		"first": {{Name: "deck", Host: "first", Description: "Deck view", URLs: pudanats.DeriveLivestreamURLs("first", "deck")}},
	}
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "idle", LatencyMS: 1, SDKVersion: "1.0", UptimeSeconds: 2, Description: "Gantry."},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var jsonBuf bytes.Buffer
	if err := writeInfoResults(&jsonBuf, results, byMachine, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Results []infoResultJSON `json:"results"`
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
	if err := writeInfoResults(&humanBuf, results, byMachine, true); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"first: pong", "Gantry.", "livestream deck: Deck view", "host: first", "hls: http://first:8888/deck/", "rtsp: rtsp://first:8554/deck", "offline: failed: timeout"} {
		if !strings.Contains(humanBuf.String(), want) {
			t.Fatalf("output missing %q: %s", want, humanBuf.String())
		}
	}
}
