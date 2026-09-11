package cli

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

func TestParseParameterTypeEquivalencePairs(t *testing.T) {
	pairs := [][2]string{
		{"Dict[str, str]", "dict[str, str]"},
		{"List[int]", "list[int]"},
		{"Optional[str]", "str | None"},
		{"Union[int, float]", "int | float"},
		{"dict[str, str]", "object[str, str]"},
		{"list[int]", "array[int]"},
		{"str | None", "string | null"},
	}
	for _, pair := range pairs {
		left, err := parseParameterType(pair[0])
		if err != nil {
			t.Fatalf("%s: %v", pair[0], err)
		}
		right, err := parseParameterType(pair[1])
		if err != nil {
			t.Fatalf("%s: %v", pair[1], err)
		}
		if !reflect.DeepEqual(left, right) {
			t.Fatalf("%s = %+v, %s = %+v", pair[0], left, pair[1], right)
		}
	}
}

func TestParseParameterTypeAcceptsRequiredForms(t *testing.T) {
	stringType := parameterType{Kind: parameterString}
	intType := parameterType{Kind: parameterInt}
	tests := []struct {
		annotation string
		want       parameterType
	}{
		{"str", stringType},
		{"string", stringType},
		{"int", intType},
		{"integer", intType},
		{"float", parameterType{Kind: parameterFloat}},
		{"number", parameterType{Kind: parameterFloat}},
		{"bool", parameterType{Kind: parameterBool}},
		{"boolean", parameterType{Kind: parameterBool}},
		{"bytes", parameterType{Kind: parameterBytes}},
		{"None", parameterType{Kind: parameterNull}},
		{"null", parameterType{Kind: parameterNull}},
		{"dict", parameterType{Kind: parameterDict}},
		{"Dict", parameterType{Kind: parameterDict}},
		{"object", parameterType{Kind: parameterDict}},
		{"dict[str, str]", parameterType{Kind: parameterDict, Values: &stringType}},
		{"dict[str, int]", parameterType{Kind: parameterDict, Values: &intType}},
		{"Dict[str, str]", parameterType{Kind: parameterDict, Values: &stringType}},
		{"Dict[str, int]", parameterType{Kind: parameterDict, Values: &intType}},
		{"object[str, str]", parameterType{Kind: parameterDict, Values: &stringType}},
		{"list", parameterType{Kind: parameterList}},
		{"List", parameterType{Kind: parameterList}},
		{"array", parameterType{Kind: parameterList}},
		{"list[str]", parameterType{Kind: parameterList, Items: &stringType}},
		{"List[str]", parameterType{Kind: parameterList, Items: &stringType}},
		{"array[str]", parameterType{Kind: parameterList, Items: &stringType}},
		{"Optional[str]", parameterType{Kind: parameterString, Nullable: true}},
		{"Union[str, None]", parameterType{Kind: parameterString, Nullable: true}},
		{"str | None", parameterType{Kind: parameterString, Nullable: true}},
		{"string | null", parameterType{Kind: parameterString, Nullable: true}},
		{"Any", parameterType{Kind: parameterAny}},
		{"typing.Dict[str, str]", parameterType{Kind: parameterDict, Values: &stringType}},
	}
	for _, test := range tests {
		got, err := parseParameterType(test.annotation)
		if err != nil {
			t.Fatalf("%s: %v", test.annotation, err)
		}
		if !reflect.DeepEqual(got, test.want) {
			t.Fatalf("%s: got %+v, want %+v", test.annotation, got, test.want)
		}
	}
}

func TestParseParameterTypeUnionIntFloatOrderIndependent(t *testing.T) {
	left, err := parseParameterType("int | float")
	if err != nil {
		t.Fatal(err)
	}
	right, err := parseParameterType("Union[float, int]")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(left, right) {
		t.Fatalf("int | float = %+v, Union[float, int] = %+v", left, right)
	}
	if left.Kind != parameterUnion || len(left.Members) != 2 {
		t.Fatalf("union schema = %+v", left)
	}
}

func TestParseParameterTypeRejectsPythonOnlyTypingForms(t *testing.T) {
	for _, annotation := range []string{
		"Literal['a', 'b']",
		"Annotated[str, 'meta']",
		`NewType("UserId", str)`,
		"Mapping[str, str]",
		"tuple[str, int]",
		"set[str]",
	} {
		_, err := parseParameterType(annotation)
		if err == nil || !strings.Contains(err.Error(), "unsupported annotation") {
			t.Fatalf("%s: error = %v", annotation, err)
		}
	}
}

func TestParseParameterTypeRejectsNonStringMappingKeys(t *testing.T) {
	_, err := parseParameterType("Dict[int, str]")
	if err == nil || !strings.Contains(err.Error(), "unsupported annotation") || !strings.Contains(err.Error(), "object keys must be str") {
		t.Fatalf("error = %v", err)
	}
	if !strings.Contains(err.Error(), "origin=Dict") || !strings.Contains(err.Error(), "args=[int, str]") {
		t.Fatalf("error is missing origin/args: %v", err)
	}
}

func TestValidateParameterizedContainerValues(t *testing.T) {
	parsed, err := parseMachineCommand(testCommand(
		"run",
		"(layout: Dict[str, str], values: list[int])",
		"Run.",
		nil,
	))
	if err != nil {
		t.Fatal(err)
	}
	valid := puda.CommandRequest{Name: "run", Params: map[string]interface{}{
		"layout": map[string]interface{}{"A2": "MEA_cell_MTP"},
		"values": []interface{}{float64(1), float64(2)},
	}}
	if errors := validateCommandParams(0, valid, parsed); len(errors) != 0 {
		t.Fatalf("valid values rejected: %+v", errors)
	}

	invalid := puda.CommandRequest{Name: "run", Params: map[string]interface{}{
		"layout": map[string]interface{}{"A2": float64(1)},
		"values": []interface{}{"a"},
	}}
	errors := validateCommandParams(0, invalid, parsed)
	if len(errors) != 2 {
		t.Fatalf("type errors = %d, want 2: %+v", len(errors), errors)
	}
}

func TestParseMachineCommandPrefersCatalogParameterSchemas(t *testing.T) {
	command := testCommand("run", "(user_id: UserId)", "Run.", nil)
	command.Parameters = map[string]pudanats.CatalogParameter{
		"user_id": {Required: true, Schema: json.RawMessage(`{"kind":"str"}`)},
	}
	parsed, err := parseMachineCommand(command)
	if err != nil {
		t.Fatal(err)
	}
	if parsed.Params["user_id"].Type.Kind != parameterString {
		t.Fatalf("schema = %+v", parsed.Params["user_id"].Type)
	}
	errors := validateCommandParams(0, puda.CommandRequest{Name: "run", Params: map[string]interface{}{"user_id": "abc"}}, parsed)
	if len(errors) != 0 {
		t.Fatalf("valid NewType value rejected: %+v", errors)
	}
}

func TestValidateAndEnrichProtocolAcceptsFirstLoadDeckLayout(t *testing.T) {
	catalog := testCatalog(
		testCommand("home", "(self) -> None", "Home the machine.", nil),
		testCommand(
			"load_deck",
			"(self, layout: Dict[str, str]) -> Dict[str, Dict[str, str | None]]",
			"Load multiple labware into the deck at once.",
			nil,
		),
	)
	protocol := validProtocol(puda.CommandRequest{
		StepNumber: 1,
		MachineID:  "first",
		Name:       "load_deck",
		Params: map[string]interface{}{
			"layout": map[string]interface{}{
				"A2": "MEA_cell_MTP",
				"C1": "trash_bin_create",
				"C2": "polyelectric_8_wellplate_30000ul",
				"C3": "opentrons_96_tiprack_300ul",
			},
		},
	})
	got, validationErrors := validateAndEnrichProtocol(protocol, func(machineID string) (pudanats.MachineCommands, error) {
		if machineID != "first" {
			t.Fatalf("unexpected machine ID %q", machineID)
		}
		return catalog, nil
	})
	if len(validationErrors) != 0 || got == nil {
		t.Fatalf("got = %+v, validation errors = %v", got, validationErrors)
	}
	if got.Commands[0].Name != "load_deck" {
		t.Fatalf("commands = %+v", got.Commands)
	}

	homeProtocol := validProtocol(puda.CommandRequest{StepNumber: 1, MachineID: "first", Name: "home"})
	got, validationErrors = validateAndEnrichProtocol(homeProtocol, func(string) (pudanats.MachineCommands, error) { return catalog, nil })
	if len(validationErrors) != 0 || got == nil {
		t.Fatalf("unrelated home command failed because load_deck is in the catalog: %v", validationErrors)
	}
}

func TestValidateAnyAndBytes(t *testing.T) {
	parsed, err := parseMachineCommand(testCommand(
		"run",
		"(payload: Any, blob: bytes, note: str | null = null)",
		"Run.",
		nil,
	))
	if err != nil {
		t.Fatal(err)
	}
	valid := puda.CommandRequest{Name: "run", Params: map[string]interface{}{
		"payload": map[string]interface{}{"ok": true}, "blob": "abc", "note": "hello",
	}}
	if errors := validateCommandParams(0, valid, parsed); len(errors) != 0 {
		t.Fatalf("valid values rejected: %+v", errors)
	}
	if errors := validateCommandParams(0, puda.CommandRequest{Name: "run", Params: map[string]interface{}{
		"payload": nil, "blob": float64(1),
	}}, parsed); len(errors) != 1 {
		t.Fatalf("errors = %+v", errors)
	}
}
