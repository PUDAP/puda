package cli

import "testing"

func TestFilterReleaseNotesBetweenUpgrade(t *testing.T) {
	releases := []githubRelease{
		{TagName: "v1.3.0"},
		{TagName: "v1.2.0"},
		{TagName: "v1.1.0"},
		{TagName: "v1.0.0"},
	}

	got := releaseTags(filterReleaseNotesBetween(releases, "v1.0.0", "v1.3.0", -1))
	want := []string{"v1.1.0", "v1.2.0", "v1.3.0"}
	assertStringSlicesEqual(t, got, want)
}

func TestFilterReleaseNotesBetweenDowngrade(t *testing.T) {
	releases := []githubRelease{
		{TagName: "v1.3.0"},
		{TagName: "v1.2.0"},
		{TagName: "v1.1.0"},
		{TagName: "v1.0.0"},
	}

	got := releaseTags(filterReleaseNotesBetween(releases, "v1.3.0", "v1.1.0", 1))
	want := []string{"v1.2.0", "v1.1.0"}
	assertStringSlicesEqual(t, got, want)
}

func TestFilterReleaseNotesBetweenSkipsUnparseableTags(t *testing.T) {
	releases := []githubRelease{
		{TagName: "latest"},
		{TagName: "v1.2.0"},
		{TagName: "nightly"},
		{TagName: "v1.1.0"},
	}

	got := releaseTags(filterReleaseNotesBetween(releases, "v1.0.0", "v1.2.0", -1))
	want := []string{"v1.1.0", "v1.2.0"}
	assertStringSlicesEqual(t, got, want)
}

func releaseTags(releases []githubRelease) []string {
	tags := make([]string, 0, len(releases))
	for _, rel := range releases {
		tags = append(tags, rel.TagName)
	}
	return tags
}

func assertStringSlicesEqual(t *testing.T, got, want []string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}
