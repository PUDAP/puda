package fleet

import "testing"

func TestIDsAreDeterministicAndNonOverlapping(t *testing.T) {
	got := IDs("load", 10001, 3)
	want := []string{"load-10001", "load-10002", "load-10003"}
	if len(got) != len(want) {
		t.Fatalf("len=%d want=%d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("IDs[%d]=%q want=%q", i, got[i], want[i])
		}
	}
}

func TestIDsSanitizePrefix(t *testing.T) {
	got := IDs("Lab.Edge", 1, 1)
	if got[0] != "lab-edge-1" {
		t.Fatalf("got %q", got[0])
	}
}
