package nats

import (
	"strings"
	"testing"
)

func TestNormalizeLivestreamName(t *testing.T) {
	got, err := NormalizeLivestreamName(" first-deck ")
	if err != nil || got != "first-deck" {
		t.Fatalf("got %q err=%v", got, err)
	}
	for _, name := range []string{"", "First", "first_deck", "-first", "first-"} {
		if _, err := NormalizeLivestreamName(name); err == nil {
			t.Fatalf("accepted %q", name)
		}
	}
}

func TestNormalizeLivestreamHost(t *testing.T) {
	got, err := NormalizeLivestreamHost(" first.taimen-truck.ts.net. ")
	if err != nil || got != "first.taimen-truck.ts.net" {
		t.Fatalf("got %q err=%v", got, err)
	}
	for _, host := range []string{"", "http://first", "first/deck", "first:8888"} {
		if _, err := NormalizeLivestreamHost(host); err == nil {
			t.Fatalf("accepted %q", host)
		}
	}
}

func TestDeriveLivestreamURLs(t *testing.T) {
	urls := DeriveLivestreamURLs("first", "first-deck")
	if urls.HLS != "http://first:8888/first-deck/" {
		t.Fatalf("hls=%q", urls.HLS)
	}
	if urls.WebRTC != "http://first:8889/first-deck/" {
		t.Fatalf("webrtc=%q", urls.WebRTC)
	}
	if urls.RTSP != "rtsp://first:8554/first-deck" {
		t.Fatalf("rtsp=%q", urls.RTSP)
	}
	if urls.RTMP != "rtmp://first:1935/first-deck" {
		t.Fatalf("rtmp=%q", urls.RTMP)
	}
}

func TestParseLivestreamUsesKeyAndNormalizesMachines(t *testing.T) {
	stream, err := parseLivestream([]byte(`{
		"name":"other",
		"host":"first",
		"description":"Top-down view.",
		"machine_ids":["first"," first ","biologic","first"]
	}`), "first-deck")
	if err != nil {
		t.Fatal(err)
	}
	if stream.Name != "first-deck" || stream.Host != "first" {
		t.Fatalf("stream=%+v", stream)
	}
	if strings.Join(stream.MachineIDs, ",") != "first,biologic" {
		t.Fatalf("machines=%v", stream.MachineIDs)
	}
	if stream.URLs.HLS != "http://first:8888/first-deck/" {
		t.Fatalf("urls=%+v", stream.URLs)
	}
}

func TestParseLivestreamMigratesLegacyURL(t *testing.T) {
	stream, err := parseLivestream([]byte(`{
		"url":"http://first.taimen-truck.ts.net:8888/livestream/",
		"description":"Legacy record."
	}`), "livestream")
	if err != nil {
		t.Fatal(err)
	}
	if stream.Host != "first.taimen-truck.ts.net" {
		t.Fatalf("host=%q", stream.Host)
	}
	if stream.URLs.RTSP != "rtsp://first.taimen-truck.ts.net:8554/livestream" {
		t.Fatalf("rtsp=%q", stream.URLs.RTSP)
	}
}

func TestValidateLivestreamRequiresHostAndDescription(t *testing.T) {
	_, err := validateLivestream(Livestream{Name: "deck", Host: "http://first", Description: "Deck"})
	if err == nil || !strings.Contains(err.Error(), "not a URL") {
		t.Fatalf("err=%v", err)
	}
	_, err = validateLivestream(Livestream{Name: "deck", Host: "first", Description: "  "})
	if err == nil || !strings.Contains(err.Error(), "description") {
		t.Fatalf("err=%v", err)
	}
}

func TestUnionAndSubtractMachineIDs(t *testing.T) {
	got := unionStrings([]string{"first"}, []string{"biologic", "first", " biologic "})
	if strings.Join(got, ",") != "first,biologic" {
		t.Fatalf("union=%v", got)
	}
	got = subtractStrings([]string{"first", "biologic", "opentrons"}, []string{"biologic", "missing"})
	if strings.Join(got, ",") != "first,opentrons" {
		t.Fatalf("subtract=%v", got)
	}
}

func TestGroupLivestreamsByMachineIsManyToMany(t *testing.T) {
	byMachine := GroupLivestreamsByMachine([]Livestream{
		{Name: "room", Host: "lab", Description: "Lab overview", MachineIDs: []string{"first", "biologic"}, URLs: DeriveLivestreamURLs("lab", "room")},
		{Name: "deck", Host: "first", Description: "Deck view", MachineIDs: []string{"first"}, URLs: DeriveLivestreamURLs("first", "deck")},
	})
	if len(byMachine["first"]) != 2 || byMachine["first"][0].Name != "deck" || byMachine["first"][1].Name != "room" {
		t.Fatalf("first=%+v", byMachine["first"])
	}
	if byMachine["first"][0].URLs.HLS != "http://first:8888/deck/" {
		t.Fatalf("deck urls=%+v", byMachine["first"][0].URLs)
	}
	if len(byMachine["biologic"]) != 1 || byMachine["biologic"][0].Host != "lab" {
		t.Fatalf("biologic=%+v", byMachine["biologic"])
	}
	if refs := LivestreamsForMachine(byMachine, "missing"); refs == nil || len(refs) != 0 {
		t.Fatalf("missing=%v", refs)
	}
}

func TestGroupLivestreamsByHostKeysByHost(t *testing.T) {
	byHost := GroupLivestreamsByHost([]Livestream{
		{Name: "room", Host: "lab", Description: "Lab overview"},
		{Name: "livestream", Host: "first", Description: "Cam 1"},
		{Name: "deck", Host: "first", Description: "Deck view"},
	})
	if len(byHost) != 2 || len(byHost["first"]) != 2 || byHost["first"]["deck"].Description != "Deck view" || byHost["first"]["livestream"].Description != "Cam 1" {
		t.Fatalf("first=%+v", byHost["first"])
	}
	if len(byHost["lab"]) != 1 || byHost["lab"]["room"].Description != "Lab overview" {
		t.Fatalf("lab=%+v", byHost["lab"])
	}
	if got := strings.Join(SortedLivestreamHosts(byHost), ","); got != "first,lab" {
		t.Fatalf("hosts=%q", got)
	}
	if got := strings.Join(SortedLivestreamNames(byHost["first"]), ","); got != "deck,livestream" {
		t.Fatalf("names=%q", got)
	}
}

func TestFilterLivestreamsByHosts(t *testing.T) {
	streams := []Livestream{
		{Name: "livestream", Host: "first"},
		{Name: "deck", Host: "first"},
		{Name: "room", Host: "lab"},
	}
	got, err := FilterLivestreamsByHosts(streams, []string{" first. "})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].Name != "livestream" || got[1].Name != "deck" {
		t.Fatalf("first-only=%+v", got)
	}
	got, err = FilterLivestreamsByHosts(streams, []string{"lab", "first"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Fatalf("both=%+v", got)
	}
	got, err = FilterLivestreamsByHosts(streams, nil)
	if err != nil || len(got) != 3 {
		t.Fatalf("all=%+v err=%v", got, err)
	}
	if _, err := FilterLivestreamsByHosts(streams, []string{"http://first"}); err == nil {
		t.Fatal("accepted URL host")
	}
}

func TestFilterLivestreamsByMachines(t *testing.T) {
	streams := []Livestream{
		{Name: "livestream", Host: "first", MachineIDs: []string{"first"}},
		{Name: "shared", Host: "lab", MachineIDs: []string{"first", "biologic"}},
		{Name: "room", Host: "lab", MachineIDs: []string{}},
	}
	got := FilterLivestreamsByMachines(streams, []string{" first "})
	if len(got) != 2 || got[0].Name != "livestream" || got[1].Name != "shared" {
		t.Fatalf("first=%+v", got)
	}
	got = FilterLivestreamsByMachines(streams, []string{"biologic"})
	if len(got) != 1 || got[0].Name != "shared" {
		t.Fatalf("biologic=%+v", got)
	}
	got = FilterLivestreamsByMachines(streams, nil)
	if len(got) != 3 {
		t.Fatalf("all=%+v", got)
	}
}
