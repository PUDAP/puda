package cli

import (
	"strings"
	"testing"
)

func TestUpdateCommandHelpIncludesReleasesURL(t *testing.T) {
	const want = "https://github.com/pudap/puda/releases"
	if !strings.Contains(updateCmd.Long, want) {
		t.Fatalf("update help must include %s", want)
	}
}

func TestUpdateCommandExposesYesFlag(t *testing.T) {
	if updateCmd.Flags().Lookup("yes") == nil {
		t.Fatal("update command must expose --yes")
	}
	if updateCmd.Flags().ShorthandLookup("y") == nil {
		t.Fatal("update command must expose -y")
	}
}

func TestResolveUpdateVersion(t *testing.T) {
	tests := []struct {
		flag    string
		args    []string
		want    string
		wantErr bool
	}{
		{flag: "", args: nil, want: ""},
		{flag: "v0.1.0-rc1", args: nil, want: "v0.1.0-rc1"},
		{flag: "", args: []string{"v0.1.0-rc1"}, want: "v0.1.0-rc1"},
		{flag: "v0.1.0", args: []string{"v0.1.0-rc1"}, wantErr: true},
	}
	for _, tc := range tests {
		got, err := resolveUpdateVersion(tc.flag, tc.args)
		if tc.wantErr {
			if err == nil {
				t.Fatalf("flag=%q args=%v: expected error", tc.flag, tc.args)
			}
			continue
		}
		if err != nil {
			t.Fatalf("flag=%q args=%v: %v", tc.flag, tc.args, err)
		}
		if got != tc.want {
			t.Fatalf("flag=%q args=%v: got %q want %q", tc.flag, tc.args, got, tc.want)
		}
	}
}
