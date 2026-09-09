package puda

import (
	"math"
	"strings"
	"testing"
	"time"
)

func TestIsWaitCommand(t *testing.T) {
	if !IsWaitCommand(CommandRequest{Name: WaitCommandName}) {
		t.Fatal("wait should be recognized")
	}
	if IsWaitCommand(CommandRequest{Name: "Wait"}) {
		t.Fatal("wait is case-sensitive")
	}
	if IsWaitCommand(CommandRequest{Name: "move_to"}) {
		t.Fatal("machine commands should not be wait")
	}
}

func TestParseWaitDuration(t *testing.T) {
	tests := []struct {
		name    string
		params  map[string]interface{}
		want    time.Duration
		wantErr string
	}{
		{name: "integer seconds", params: map[string]interface{}{"seconds": float64(5)}, want: 5 * time.Second},
		{name: "fractional seconds", params: map[string]interface{}{"seconds": 0.5}, want: 500 * time.Millisecond},
		{name: "zero", params: map[string]interface{}{"seconds": float64(0)}, want: 0},
		{name: "native int", params: map[string]interface{}{"seconds": 2}, want: 2 * time.Second},
		{name: "missing", params: map[string]interface{}{}, wantErr: "required parameter seconds is missing"},
		{name: "nil params", params: nil, wantErr: "required parameter seconds is missing"},
		{name: "string", params: map[string]interface{}{"seconds": "5"}, wantErr: "must be a number"},
		{name: "negative", params: map[string]interface{}{"seconds": float64(-1)}, wantErr: "greater than or equal to 0"},
		{name: "nan", params: map[string]interface{}{"seconds": math.NaN()}, wantErr: "finite number"},
		{name: "inf", params: map[string]interface{}{"seconds": math.Inf(1)}, wantErr: "finite number"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := ParseWaitDuration(test.params)
			if test.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), test.wantErr) {
					t.Fatalf("error = %v, want %q", err, test.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got != test.want {
				t.Fatalf("duration = %s, want %s", got, test.want)
			}
		})
	}
}

func TestValidateCommandStructureAllowsWaitWithoutMachineID(t *testing.T) {
	errors := ValidateCommandStructure([]CommandRequest{
		{Name: "wait", StepNumber: 1, Params: map[string]interface{}{"seconds": float64(2)}},
		{Name: "home", MachineID: "machine-1", StepNumber: 2},
	})
	if len(errors) != 0 {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateCommandStructureRejectsWaitWithoutSeconds(t *testing.T) {
	errors := ValidateCommandStructure([]CommandRequest{
		{Name: "wait", StepNumber: 1},
	})
	if len(errors) != 1 || errors[0].Field != "params.seconds" || !strings.Contains(errors[0].Message, "missing") {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateCommandStructureRejectsUnknownWaitParams(t *testing.T) {
	errors := ValidateCommandStructure([]CommandRequest{
		{Name: "wait", StepNumber: 1, Params: map[string]interface{}{"seconds": float64(1), "milliseconds": float64(500)}},
	})
	if len(errors) != 1 || errors[0].Field != "params.milliseconds" {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateCommandStructureRejectsWaitKwargs(t *testing.T) {
	errors := ValidateCommandStructure([]CommandRequest{
		{Name: "wait", StepNumber: 1, Params: map[string]interface{}{"seconds": float64(1)}, Kwargs: map[string]interface{}{"seconds": float64(1)}},
	})
	if len(errors) != 1 || errors[0].Field != "kwargs" {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateCommandStructureRejectsWaitAndCommandForSameMachineAtSameStep(t *testing.T) {
	errors := ValidateCommandStructure([]CommandRequest{
		{Name: "home", MachineID: "machine-1", StepNumber: 1},
		{Name: "wait", MachineID: "machine-1", StepNumber: 1, Params: map[string]interface{}{"seconds": float64(1)}},
	})
	if len(errors) != 1 || errors[0].Field != "step_number" || !strings.Contains(errors[0].Message, "duplicates") {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateCommandStructureAllowsWaitForSomeMachinesInAParallelStep(t *testing.T) {
	errors := ValidateCommandStructure([]CommandRequest{
		{Name: "wait", MachineID: "machine-1", StepNumber: 1, Params: map[string]interface{}{"seconds": float64(5)}},
		{Name: "home", MachineID: "machine-2", StepNumber: 1},
	})
	if len(errors) != 0 {
		t.Fatalf("errors = %+v", errors)
	}
}
