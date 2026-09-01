package cli

import (
	"bytes"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

func boolPointer(value bool) *bool { return &value }

func TestWriteProtocolValidationSuccessPrintsOnlyPassed(t *testing.T) {
	var output bytes.Buffer
	if err := writeProtocolValidationSuccess(&output); err != nil {
		t.Fatal(err)
	}
	if got, want := output.String(), "passed\n"; got != want {
		t.Fatalf("output = %q, want %q", got, want)
	}
}

func testCatalog(entries ...pudanats.MachineCommand) pudanats.MachineCommands {
	return pudanats.MachineCommands{Commands: "human text must not be parsed", Catalog: entries}
}

func testCommand(name, signature, doc string, safety *pudanats.MachineCommandSafety) pudanats.MachineCommand {
	return pudanats.MachineCommand{Name: name, Signature: signature, Doc: &doc, DocPresent: true, Safety: safety, SafetyPresent: true}
}

func moveCatalog() pudanats.MachineCommands {
	return testCatalog(testCommand(
		"move_to",
		"(x: float, y: float, z: float) -> dict",
		"Move to an absolute simulated position.",
		&pudanats.MachineCommandSafety{
			Summary:       "Confirm the workspace is clear before moving.",
			Hazards:       []string{"collision"},
			Requires:      stringPointer("Machine must just have been homed and the workspace clear."),
			ForbiddenWhen: stringPointer("Do not move if the workspace is occupied, human movement is detected"),
			Confirm:       boolPointer(true),
		},
	))
}

func stringPointer(value string) *string { return &value }

func validProtocol(commands ...puda.CommandRequest) *puda.ProtocolFile {
	return &puda.ProtocolFile{Commands: commands}
}

func TestValidateAndEnrichProtocolUsesStructuredCatalogAndSafety(t *testing.T) {
	protocol := validProtocol(puda.CommandRequest{
		StepNumber: 1,
		MachineID:  "machine-001",
		Name:       "move_to",
		Params: map[string]interface{}{
			"x": float64(1), "y": float64(1), "z": float64(1),
		},
	})

	got, validationErrors := validateAndEnrichProtocol(protocol, func(machineID string) (pudanats.MachineCommands, error) {
		if machineID != "machine-001" {
			t.Fatalf("unexpected machine ID %q", machineID)
		}
		return moveCatalog(), nil
	})

	if len(validationErrors) != 0 || got == nil {
		t.Fatalf("got = %+v, validation errors = %v", got, validationErrors)
	}
	command := got.Commands[0]
	if command.Description != "Move to an absolute simulated position." || command.Safety == nil {
		t.Fatalf("structured metadata was not preserved: %+v", command)
	}
	if command.Safety.Summary != "Confirm the workspace is clear before moving." || !command.Safety.Confirm {
		t.Fatalf("safety = %+v", command.Safety)
	}
	if command.Safety.Requires != "Machine must just have been homed and the workspace clear." {
		t.Fatalf("requires = %q", command.Safety.Requires)
	}
	if command.Safety.ForbiddenWhen != "Do not move if the workspace is occupied, human movement is detected" {
		t.Fatalf("forbidden_when = %q", command.Safety.ForbiddenWhen)
	}
}

func TestValidateAndEnrichProtocolRejectsMalformedStructuredCatalog(t *testing.T) {
	tests := []struct {
		name    string
		catalog pudanats.MachineCommands
	}{
		{name: "missing catalog", catalog: pudanats.MachineCommands{}},
		{name: "missing name", catalog: testCatalog(testCommand("", "(x: int)", "doc", nil))},
		{name: "missing signature", catalog: testCatalog(testCommand("run", "", "doc", nil))},
		{name: "missing doc field", catalog: testCatalog(pudanats.MachineCommand{Name: "run", Signature: "(x: int)", SafetyPresent: true})},
		{name: "missing safety field", catalog: testCatalog(pudanats.MachineCommand{Name: "run", Signature: "(x: int)", Doc: stringPointer("doc")})},
		{name: "malformed safety", catalog: testCatalog(testCommand("run", "(x: int)", "doc", &pudanats.MachineCommandSafety{Summary: "safe", Confirm: nil}))},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			protocol := validProtocol(puda.CommandRequest{StepNumber: 1, MachineID: "machine", Name: "run", Params: map[string]interface{}{"x": float64(1)}})
			got, validationErrors := validateAndEnrichProtocol(protocol, func(string) (pudanats.MachineCommands, error) { return test.catalog, nil })
			if got != nil || len(validationErrors) == 0 {
				t.Fatalf("got = %+v, errors = %v", got, validationErrors)
			}
			if !strings.Contains(validationErrors[0].Message, "catalog") {
				t.Fatalf("error = %+v", validationErrors[0])
			}
		})
	}
}

func TestValidateCommandParamsRejectsDuplicateNamesAcrossParamsAndKwargs(t *testing.T) {
	command := puda.CommandRequest{Name: "run", Params: map[string]interface{}{"x": float64(1)}, Kwargs: map[string]interface{}{"x": float64(2)}}
	parsed := parsedMachineCommand{Params: map[string]parsedMachineParam{"x": {Required: true, Type: parameterType{Kinds: []parameterKind{parameterFloat}}}}}

	errors := validateCommandParams(0, command, parsed)
	if len(errors) != 1 || errors[0].Field != "kwargs.x" || !strings.Contains(errors[0].Message, "both params and kwargs") {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateAndEnrichProtocolBoundsCatalogFetchConcurrency(t *testing.T) {
	var mutex sync.Mutex
	active, maximum := 0, 0
	commands := make([]puda.CommandRequest, 12)
	for index := range commands {
		commands[index] = puda.CommandRequest{StepNumber: index + 1, MachineID: fmt.Sprintf("machine-%02d", index), Name: "home"}
	}

	_, validationErrors := validateAndEnrichProtocol(validProtocol(commands...), func(string) (pudanats.MachineCommands, error) {
		mutex.Lock()
		active++
		if active > maximum {
			maximum = active
		}
		mutex.Unlock()
		time.Sleep(time.Millisecond)
		mutex.Lock()
		active--
		mutex.Unlock()
		return testCatalog(testCommand("home", "() -> None", "Home.", nil)), nil
	})

	if len(validationErrors) != 0 {
		t.Fatalf("validation errors = %v", validationErrors)
	}
	if maximum > machineCatalogWorkerLimit {
		t.Fatalf("maximum concurrent fetches = %d, limit = %d", maximum, machineCatalogWorkerLimit)
	}
}

func TestValidateAndEnrichProtocolAggregatesCatalogErrorWhenNameIsMissing(t *testing.T) {
	protocol := validProtocol(puda.CommandRequest{StepNumber: 1, MachineID: "machine", Name: ""})
	got, validationErrors := validateAndEnrichProtocol(protocol, func(machineID string) (pudanats.MachineCommands, error) {
		return pudanats.MachineCommands{}, fmt.Errorf("catalog unavailable")
	})

	if got != nil {
		t.Fatalf("got partially enriched protocol: %+v", got)
	}
	if len(validationErrors) != 2 {
		t.Fatalf("validation errors = %d, want 2: %v", len(validationErrors), validationErrors)
	}
	if validationErrors[0].Field != "name" || validationErrors[1].Field != "machine_id" {
		t.Fatalf("errors are not deterministic: %+v", validationErrors)
	}
}

func TestValidateAndEnrichProtocolAggregatesStructuralAndResolvableCatalogErrors(t *testing.T) {
	protocol := validProtocol(
		puda.CommandRequest{StepNumber: 0, MachineID: "machine", Name: "missing"},
		puda.CommandRequest{StepNumber: 1, MachineID: "", Name: "also_missing"},
	)
	got, validationErrors := validateAndEnrichProtocol(protocol, func(machineID string) (pudanats.MachineCommands, error) {
		if machineID != "machine" {
			t.Fatalf("attempted to resolve invalid machine ID %q", machineID)
		}
		return testCatalog(testCommand("home", "()", "Home.", nil)), nil
	})

	if got != nil {
		t.Fatalf("got partially enriched protocol: %+v", got)
	}
	if len(validationErrors) != 3 {
		t.Fatalf("validation errors = %d, want 3: %v", len(validationErrors), validationErrors)
	}
	if validationErrors[0].Field != "step_number" || validationErrors[1].Field != "name" || validationErrors[2].Field != "machine_id" {
		t.Fatalf("errors are not deterministic: %+v", validationErrors)
	}
}

func TestValidateCommandParamsChecksBasicAnnotationTypesAndNullability(t *testing.T) {
	parsed, err := parseMachineCommand(testCommand("run", "(count: 'int', ratio: 'float', label: 'str', enabled: 'bool', options: 'dict', values: 'list', note: 'str | None' = None)", "Run.", nil))
	if err != nil {
		t.Fatal(err)
	}
	valid := puda.CommandRequest{Name: "run", Params: map[string]interface{}{
		"count": float64(2), "ratio": float64(2.5), "label": "ok", "enabled": true,
		"options": map[string]interface{}{}, "values": []interface{}{}, "note": nil,
	}}
	if errors := validateCommandParams(0, valid, parsed); len(errors) != 0 {
		t.Fatalf("valid values rejected: %+v", errors)
	}

	invalid := valid
	invalid.Params = map[string]interface{}{
		"count": float64(2.5), "ratio": "2.5", "label": true, "enabled": float64(1),
		"options": []interface{}{}, "values": map[string]interface{}{}, "note": float64(1),
	}
	errors := validateCommandParams(0, invalid, parsed)
	if len(errors) != 7 {
		t.Fatalf("type errors = %d, want 7: %+v", len(errors), errors)
	}
}

func TestParseMachineCommandRejectsNullForNonNullableAndUnknownAnnotation(t *testing.T) {
	parsed, err := parseMachineCommand(testCommand("run", "(x: int)", "Run.", nil))
	if err != nil {
		t.Fatal(err)
	}
	errors := validateCommandParams(0, puda.CommandRequest{Name: "run", Params: map[string]interface{}{"x": nil}}, parsed)
	if len(errors) != 1 || !strings.Contains(errors[0].Message, "does not allow null") {
		t.Fatalf("errors = %+v", errors)
	}

	_, err = parseMachineCommand(testCommand("run", "(values: list[int])", "Run.", nil))
	if err == nil || !strings.Contains(err.Error(), "unsupported annotation") {
		t.Fatalf("error = %v", err)
	}
}

func TestParseMachineCommandRejectsPositionalOnlySignature(t *testing.T) {
	_, err := parseMachineCommand(testCommand("run", "(x: int, /, y: int)", "Run.", nil))
	if err == nil || !strings.Contains(err.Error(), "positional-only") {
		t.Fatalf("error = %v", err)
	}
}

func TestParseMachineCommandMatchesSignatureParentheses(t *testing.T) {
	parsed, err := parseMachineCommand(testCommand("run", "(callback: Callable[[int], str] = factory(1)) -> None", "Run.", nil))
	if err == nil || !strings.Contains(err.Error(), "unsupported annotation") {
		t.Fatalf("balanced signature was parsed incorrectly: parsed=%+v err=%v", parsed, err)
	}

	_, err = parseMachineCommand(testCommand("run", "(x: int", "Run.", nil))
	if err == nil || !strings.Contains(err.Error(), "unbalanced") {
		t.Fatalf("error = %v", err)
	}
}

func TestValidateAndEnrichProtocolReturnsErrorsInProtocolOrderDespiteFetchCompletionOrder(t *testing.T) {
	protocol := validProtocol(
		puda.CommandRequest{StepNumber: 1, MachineID: "slow", Name: "missing"},
		puda.CommandRequest{StepNumber: 2, MachineID: "fast", Name: "missing"},
	)
	_, errors := validateAndEnrichProtocol(protocol, func(machineID string) (pudanats.MachineCommands, error) {
		if machineID == "slow" {
			time.Sleep(time.Millisecond)
		}
		return testCatalog(testCommand("home", "()", "Home.", nil)), nil
	})
	if len(errors) != 2 || errors[0].CommandIndex != 0 || errors[1].CommandIndex != 1 {
		t.Fatalf("errors are not in protocol order: %+v", errors)
	}
}

func TestValidateCommandStructureRequiresStepNumbersToStartAtOne(t *testing.T) {
	errors := puda.ValidateCommandStructure([]puda.CommandRequest{
		{Name: "home", MachineID: "machine-1", StepNumber: 0},
		{Name: "move", MachineID: "machine-1", StepNumber: 1},
	})
	if len(errors) != 1 || errors[0].CommandIndex != 0 || errors[0].Field != "step_number" || !strings.Contains(errors[0].Message, "start at 1") {
		t.Fatalf("errors = %+v", errors)
	}
}

func TestValidateCommandStructureAllowsParallelCommandsStartingAtOne(t *testing.T) {
	errors := puda.ValidateCommandStructure([]puda.CommandRequest{
		{Name: "home", MachineID: "machine-1", StepNumber: 1},
		{Name: "home", MachineID: "machine-2", StepNumber: 1},
		{Name: "move", MachineID: "machine-1", StepNumber: 2},
	})
	if len(errors) != 0 {
		t.Fatalf("errors = %+v", errors)
	}
}
