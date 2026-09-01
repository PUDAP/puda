package cli

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"reflect"
	"strings"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

func TestConfirmProtocolStepDisplaysWholeCommandAndSafetyAndAcceptsYes(t *testing.T) {
	commands := []puda.CommandRequest{{
		StepNumber: 2,
		MachineID:  "machine-001",
		Name:       "move_to",
		Params:     map[string]interface{}{"x": float64(1), "y": float64(1), "z": float64(1)},
		Safety: &puda.CommandSafety{
			Summary:       "Confirm the workspace is clear before moving.",
			Hazards:       []string{"collision"},
			Requires:      "Machine must just have been homed and the workspace clear.",
			ForbiddenWhen: "Do not move if the workspace is occupied, human movement is detected",
			Confirm:       true,
		},
	}}
	var output bytes.Buffer

	err := confirmProtocolStep(context.Background(), bufio.NewReader(strings.NewReader("yes\n")), &output, 2, commands)
	if err != nil {
		t.Fatal(err)
	}
	text := output.String()
	for _, expected := range []string{
		"Safety confirmation required for step 2",
		`"machine_id": "machine-001"`,
		`"name": "move_to"`,
		`"summary": "Confirm the workspace is clear before moving."`,
		`"hazards": [`,
		`"requires": "Machine must just have been homed and the workspace clear."`,
		`"forbidden_when": "Do not move if the workspace is occupied, human movement is detected"`,
		`"confirm": true`,
		"Type yes to continue step 2:",
	} {
		if !strings.Contains(text, expected) {
			t.Fatalf("output missing %q:\n%s", expected, text)
		}
	}
}

func TestConfirmProtocolStepRejectsAnythingExceptYes(t *testing.T) {
	commands := []puda.CommandRequest{{
		StepNumber: 1,
		MachineID:  "machine-001",
		Name:       "move_to",
		Safety:     &puda.CommandSafety{Summary: "Motion risk.", Hazards: []string{}, Requires: "Workspace clear.", ForbiddenWhen: "Human detected.", Confirm: true},
	}}
	var output bytes.Buffer

	err := confirmProtocolStep(context.Background(), bufio.NewReader(strings.NewReader("no\n")), &output, 1, commands)
	if err == nil || !strings.Contains(err.Error(), "not confirmed") {
		t.Fatalf("error = %v", err)
	}
}

func TestConfirmProtocolStepDoesNothingWithoutRequiredConfirmation(t *testing.T) {
	commands := []puda.CommandRequest{
		{StepNumber: 1, MachineID: "machine-001", Name: "home"},
		{StepNumber: 1, MachineID: "machine-002", Name: "move", Safety: &puda.CommandSafety{Summary: "Advisory.", Confirm: false}},
	}
	var output bytes.Buffer

	err := confirmProtocolStep(context.Background(), bufio.NewReader(strings.NewReader("")), &output, 1, commands)
	if err != nil {
		t.Fatal(err)
	}
	if output.Len() != 0 {
		t.Fatalf("unexpected output: %q", output.String())
	}
}

func TestConfirmProtocolStepReusesBufferedInputAcrossSteps(t *testing.T) {
	reader := bufio.NewReader(strings.NewReader("yes\nyes\n"))
	command := []puda.CommandRequest{{
		StepNumber: 1,
		MachineID:  "machine",
		Name:       "move",
		Safety:     &puda.CommandSafety{Summary: "Motion risk.", Confirm: true},
	}}
	var output bytes.Buffer

	if err := confirmProtocolStep(context.Background(), reader, &output, 1, command); err != nil {
		t.Fatal(err)
	}
	command[0].StepNumber = 2
	if err := confirmProtocolStep(context.Background(), reader, &output, 2, command); err != nil {
		t.Fatal(err)
	}
}

func TestConfirmProtocolStepStopsWaitingWhenContextIsCancelled(t *testing.T) {
	readEnd, writeEnd := io.Pipe()
	defer readEnd.Close()
	defer writeEnd.Close()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	commands := []puda.CommandRequest{{
		StepNumber: 1,
		MachineID:  "machine",
		Name:       "move",
		Safety:     &puda.CommandSafety{Summary: "Motion risk.", Confirm: true},
	}}

	err := confirmProtocolStep(ctx, bufio.NewReader(readEnd), io.Discard, 1, commands)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context canceled", err)
	}
}

func TestAuthoritativeProtocolForRunReplacesEditableSafetyWithLiveCatalogSafety(t *testing.T) {
	protocol := validProtocol(puda.CommandRequest{
		StepNumber: 1,
		MachineID:  "machine-001",
		Name:       "move_to",
		Params:     map[string]interface{}{"x": float64(1), "y": float64(1), "z": float64(1)},
		Safety:     &puda.CommandSafety{Summary: "edited", Confirm: false},
	})

	resolved, validationErrors := authoritativeProtocolForRun(protocol, func(string) (nats.MachineCommands, error) {
		return moveCatalog(), nil
	})

	if len(validationErrors) != 0 || resolved == nil {
		t.Fatalf("resolved = %+v, validation errors = %v", resolved, validationErrors)
	}
	safety := resolved.Commands[0].Safety
	if safety == nil || !safety.Confirm || safety.Summary != "Confirm the workspace is clear before moving." {
		t.Fatalf("run safety was not replaced from the live catalog: %+v", safety)
	}
	if safety.Requires != "Machine must just have been homed and the workspace clear." || safety.ForbiddenWhen != "Do not move if the workspace is occupied, human movement is detected" {
		t.Fatalf("live safety prose was not preserved as strings: %+v", safety)
	}
	if protocol.Commands[0].Safety == nil || protocol.Commands[0].Safety.Summary != "edited" {
		t.Fatalf("input protocol was mutated: %+v", protocol.Commands[0].Safety)
	}
}

func TestAuthoritativeProtocolForRunFailsClosedWhenLiveCatalogCannotBeResolved(t *testing.T) {
	protocol := validProtocol(puda.CommandRequest{StepNumber: 1, MachineID: "machine-001", Name: "move_to"})

	resolved, validationErrors := authoritativeProtocolForRun(protocol, func(string) (nats.MachineCommands, error) {
		return nats.MachineCommands{}, errors.New("catalog unavailable")
	})

	if resolved != nil || len(validationErrors) == 0 {
		t.Fatalf("resolved = %+v, validation errors = %v", resolved, validationErrors)
	}
}

func TestProtocolStepRangesDefaultsToFullProtocol(t *testing.T) {
	cmd := &cobra.Command{}
	cmd.Flags().StringVar(&protocolSteps, "steps", "", "")

	got, err := protocolStepRanges(cmd)
	if err != nil {
		t.Fatalf("protocolStepRanges() returned error: %v", err)
	}
	if got != nil {
		t.Fatalf("protocolStepRanges() = %#v, want nil", got)
	}
}

func TestParseProtocolSteps(t *testing.T) {
	tests := []struct {
		name    string
		value   string
		want    []nats.StepRange
		wantErr bool
	}{
		{
			name:  "single step",
			value: "3",
			want: []nats.StepRange{
				{StartStep: 3, EndStep: 3},
			},
		},
		{
			name:  "bounded range",
			value: "2-5",
			want: []nats.StepRange{
				{StartStep: 2, EndStep: 5},
			},
		},
		{
			name:  "open ended range",
			value: "2-",
			want: []nats.StepRange{
				{StartStep: 2, EndStep: 0},
			},
		},
		{
			name:  "implicit start",
			value: "-5",
			want: []nats.StepRange{
				{StartStep: 1, EndStep: 5},
			},
		},
		{
			name:  "comma separated selectors",
			value: "4,6-7,10-",
			want: []nats.StepRange{
				{StartStep: 4, EndStep: 4},
				{StartStep: 6, EndStep: 7},
				{StartStep: 10, EndStep: 0},
			},
		},
		{
			name:    "empty",
			value:   "",
			wantErr: true,
		},
		{
			name:    "zero",
			value:   "0",
			wantErr: true,
		},
		{
			name:    "end before start",
			value:   "5-2",
			wantErr: true,
		},
		{
			name:    "too many ranges",
			value:   "1-2-3",
			wantErr: true,
		},
		{
			name:    "empty selector",
			value:   "1,,3",
			wantErr: true,
		},
		{
			name:    "not a number",
			value:   "two-five",
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseProtocolSteps(tt.value)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("parseProtocolSteps(%q) returned no error", tt.value)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseProtocolSteps(%q) returned error: %v", tt.value, err)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("parseProtocolSteps(%q) = %#v, want %#v", tt.value, got, tt.want)
			}
		})
	}
}
