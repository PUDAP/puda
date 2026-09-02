package cli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

func TestLivestreamCommandMetadata(t *testing.T) {
	if livestreamCmd.Use != "livestream" {
		t.Fatalf("Use=%q", livestreamCmd.Use)
	}
	if livestreamAddCmd.Flags().Lookup("name") == nil || livestreamAddCmd.Flags().Lookup("host") == nil || livestreamAddCmd.Flags().Lookup("description") == nil {
		t.Fatal("add must expose --name --host --description")
	}
	if livestreamAddCmd.Flags().Lookup("url") != nil {
		t.Fatal("add must not expose --url")
	}
	if livestreamListCmd.Use != "list" {
		t.Fatalf("list Use=%q", livestreamListCmd.Use)
	}
	if livestreamListCmd.Flags().Lookup("hosts") == nil || livestreamListCmd.Flags().Lookup("machines") == nil {
		t.Fatal("list must expose --hosts and --machines")
	}
	if livestreamAttachCmd.Flags().Lookup("machines") == nil || livestreamDetachCmd.Flags().Lookup("machines") == nil {
		t.Fatal("attach/detach must expose --machines")
	}
	found := map[string]bool{}
	for _, cmd := range livestreamCmd.Commands() {
		found[cmd.Name()] = true
	}
	for _, name := range []string{"add", "list", "rm", "attach", "detach"} {
		if !found[name] {
			t.Fatalf("missing subcommand %s", name)
		}
	}
}

func TestWriteLivestreamListJSONAndHuman(t *testing.T) {
	streams := []pudanats.Livestream{
		{Name: "deck", Host: "first", Description: "Deck view", MachineIDs: []string{"first", "biologic"}, URLs: pudanats.DeriveLivestreamURLs("first", "deck")},
		{Name: "livestream", Host: "first", Description: "Cam 1", MachineIDs: []string{"first"}, URLs: pudanats.DeriveLivestreamURLs("first", "livestream")},
		{Name: "room", Host: "lab", Description: "Lab overview", MachineIDs: []string{}, URLs: pudanats.DeriveLivestreamURLs("lab", "room")},
	}
	var jsonBuf bytes.Buffer
	if err := writeLivestreamList(&jsonBuf, streams, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Livestreams map[string]map[string]livestreamListItem `json:"livestreams"`
		Count       int                                      `json:"count"`
	}
	if err := json.Unmarshal(jsonBuf.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Count != 3 || len(payload.Livestreams) != 2 {
		t.Fatalf("got %+v", payload)
	}
	if payload.Livestreams["first"]["deck"].Description != "Deck view" || payload.Livestreams["first"]["livestream"].Description != "Cam 1" {
		t.Fatalf("first=%+v", payload.Livestreams["first"])
	}
	if payload.Livestreams["first"]["deck"].URLs.HLS != "http://first:8888/deck/" {
		t.Fatalf("urls=%+v", payload.Livestreams["first"]["deck"].URLs)
	}
	if payload.Livestreams["lab"]["room"].Description != "Lab overview" {
		t.Fatalf("lab=%+v", payload.Livestreams["lab"])
	}

	var humanBuf bytes.Buffer
	if err := writeLivestreamList(&humanBuf, streams, true); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"3 livestreams on 2 hosts:", "  first:", "    deck: Deck view", "    livestream: Cam 1", "  lab:", "    room: Lab overview", "hls: http://first:8888/deck/", "machines: first, biologic", "machines: no machines"} {
		if !strings.Contains(humanBuf.String(), want) {
			t.Fatalf("output missing %q: %s", want, humanBuf.String())
		}
	}

	var empty bytes.Buffer
	if err := writeLivestreamList(&empty, nil, true); err != nil {
		t.Fatal(err)
	}
	if got := empty.String(); got != "No livestreams registered.\n" {
		t.Fatalf("empty=%q", got)
	}
}

func TestWriteLivestreamListFiltersToRequestedHosts(t *testing.T) {
	streams := []pudanats.Livestream{
		{Name: "deck", Host: "first", Description: "Deck view", MachineIDs: []string{"first"}, URLs: pudanats.DeriveLivestreamURLs("first", "deck")},
		{Name: "room", Host: "lab", Description: "Lab overview", MachineIDs: []string{}, URLs: pudanats.DeriveLivestreamURLs("lab", "room")},
	}
	filtered, err := pudanats.FilterLivestreamsByHosts(streams, []string{"first"})
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := writeLivestreamList(&buf, filtered, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Livestreams map[string]map[string]livestreamListItem `json:"livestreams"`
		Count       int                                      `json:"count"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Count != 1 || len(payload.Livestreams) != 1 || payload.Livestreams["lab"] != nil {
		t.Fatalf("got %+v", payload)
	}
	if payload.Livestreams["first"]["deck"].Description != "Deck view" {
		t.Fatalf("first=%+v", payload.Livestreams["first"])
	}
}

func TestWriteLivestreamListFiltersToRequestedMachines(t *testing.T) {
	streams := []pudanats.Livestream{
		{Name: "deck", Host: "first", Description: "Deck view", MachineIDs: []string{"first"}, URLs: pudanats.DeriveLivestreamURLs("first", "deck")},
		{Name: "shared", Host: "lab", Description: "Shared cam", MachineIDs: []string{"first", "biologic"}, URLs: pudanats.DeriveLivestreamURLs("lab", "shared")},
		{Name: "room", Host: "lab", Description: "Lab overview", MachineIDs: []string{}, URLs: pudanats.DeriveLivestreamURLs("lab", "room")},
	}
	filtered := pudanats.FilterLivestreamsByMachines(streams, []string{"biologic"})
	var buf bytes.Buffer
	if err := writeLivestreamList(&buf, filtered, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Livestreams map[string]map[string]livestreamListItem `json:"livestreams"`
		Count       int                                      `json:"count"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Count != 1 || payload.Livestreams["first"] != nil {
		t.Fatalf("got %+v", payload)
	}
	if payload.Livestreams["lab"]["shared"].Description != "Shared cam" {
		t.Fatalf("lab=%+v", payload.Livestreams["lab"])
	}
	if _, ok := payload.Livestreams["lab"]["room"]; ok {
		t.Fatalf("unexpected room: %+v", payload.Livestreams["lab"])
	}
}
