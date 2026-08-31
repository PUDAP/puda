package cli

import (
	"strings"
	"testing"
)

const sampleMachineCommands = `get_position(self) -> dict[str, float]
    Current simulated cartesian position (telemetry only).

home(self) -> dict
    Home the machine. Used by puda machine home fake.

    Returns:
        dict: Homed flag and origin position

move(self, x: float) -> dict
    Move along X.

move_to(self, x: float, y: float, z: float) -> dict
    Move to an absolute simulated position.
    safety:
        Confirm the workspace is clear before moving.
        hazards: collision
        requires: Machine must just have been homed and the workspace clear.
        forbidden_when: Do not move if the workspace is occupied, human movement is detected
        confirm: true

    Args:
        x: Target X
        y: Target Y
        z: Target Z

    Returns:
        dict: New position

echo(self, message: str = '') -> dict
    Echo a string back. Useful for round-trip command tests.
`

func TestMachineCommandsCommandMetadata(t *testing.T) {
	if got, want := machineCommandsCmd.Use, "commands <machine_id>"; got != want {
		t.Fatalf("Use=%q want=%q", got, want)
	}
	if !strings.Contains(machineCommandsCmd.Long, "comma-separated") {
		t.Fatalf("Long=%q, want comma-separated documentation", machineCommandsCmd.Long)
	}
	if machineCommandsCmd.Flags().Lookup("command") == nil {
		t.Fatal("commands command must expose --command")
	}
}

func TestExtractMachineCommandText(t *testing.T) {
	got, err := extractMachineCommandText(sampleMachineCommands, "move_to")
	if err != nil {
		t.Fatal(err)
	}

	want := `move_to(self, x: float, y: float, z: float) -> dict
    Move to an absolute simulated position.
    safety:
        Confirm the workspace is clear before moving.
        hazards: collision
        requires: Machine must just have been homed and the workspace clear.
        forbidden_when: Do not move if the workspace is occupied, human movement is detected
        confirm: true

    Args:
        x: Target X
        y: Target Y
        z: Target Z

    Returns:
        dict: New position`
	if got != want {
		t.Fatalf("extractMachineCommandText() =\n%s\nwant\n%s", got, want)
	}
	if strings.Contains(got, "echo(") || strings.Contains(got, "move(self") {
		t.Fatalf("extracted more than one command:\n%s", got)
	}
}

func TestExtractMachineCommandTextDoesNotMatchPrefix(t *testing.T) {
	got, err := extractMachineCommandText(sampleMachineCommands, "move")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(got, "move(self, x: float) -> dict") {
		t.Fatalf("got %q", got)
	}
	if strings.Contains(got, "move_to") {
		t.Fatalf("prefix matched move_to:\n%s", got)
	}
}

func TestExtractMachineCommandTextNotFound(t *testing.T) {
	_, err := extractMachineCommandText(sampleMachineCommands, "missing")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), `command "missing" not found`) {
		t.Fatalf("error = %v", err)
	}
	if !strings.Contains(err.Error(), "move_to") || !strings.Contains(err.Error(), "home") {
		t.Fatalf("error should list available commands: %v", err)
	}
}

func TestExtractMachineCommandTextCommaSeparated(t *testing.T) {
	got, err := extractMachineCommandText(sampleMachineCommands, "echo, home")
	if err != nil {
		t.Fatal(err)
	}

	want := `echo(self, message: str = '') -> dict
    Echo a string back. Useful for round-trip command tests.

home(self) -> dict
    Home the machine. Used by puda machine home fake.

    Returns:
        dict: Homed flag and origin position`
	if got != want {
		t.Fatalf("extractMachineCommandText() =\n%s\nwant\n%s", got, want)
	}
	if strings.Contains(got, "move_to") || strings.Contains(got, "get_position") {
		t.Fatalf("extracted extra commands:\n%s", got)
	}
}

func TestExtractMachineCommandTextDedupesNames(t *testing.T) {
	got, err := extractMachineCommandText(sampleMachineCommands, "home,home")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(got, "home(self)") != 1 {
		t.Fatalf("expected home once, got:\n%s", got)
	}
}

func TestExtractMachineCommandTextMultipleMissing(t *testing.T) {
	_, err := extractMachineCommandText(sampleMachineCommands, "missing,home,also_missing")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), `commands "missing", "also_missing" not found`) {
		t.Fatalf("error = %v", err)
	}
}

func TestParseCommandNames(t *testing.T) {
	got := parseCommandNames(" echo, home,echo ,")
	want := "echo,home"
	if strings.Join(got, ",") != want {
		t.Fatalf("parseCommandNames() = %v, want %v", got, []string{"echo", "home"})
	}
}

func TestExtractMachineCommandTextEmptyNames(t *testing.T) {
	_, err := extractMachineCommandText(sampleMachineCommands, " , ")
	if err == nil || err.Error() != "at least one command name is required" {
		t.Fatalf("error = %v", err)
	}
}

func TestExtractMachineCommandTextEmptyCatalog(t *testing.T) {
	_, err := extractMachineCommandText("", "home")
	if err == nil || err.Error() != `command "home" not found` {
		t.Fatalf("error = %v", err)
	}
}

func TestSplitMachineCommandBlocksPreservesOrder(t *testing.T) {
	blocks := splitMachineCommandBlocks(sampleMachineCommands)
	got := make([]string, 0, len(blocks))
	for _, block := range blocks {
		got = append(got, block.Name)
	}
	want := []string{"get_position", "home", "move", "move_to", "echo"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("names = %v, want %v", got, want)
	}
}
