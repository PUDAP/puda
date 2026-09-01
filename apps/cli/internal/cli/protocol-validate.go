package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"sort"
	"strings"
	"sync"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

const machineCatalogWorkerLimit = 4

var protocolValidateCmd = &cobra.Command{
	Use:   "validate",
	Short: "Validate and resolve a protocol JSON file",
	Long: `Validate a protocol JSON file against each target machine's advertised commands.

The command validates the complete protocol before producing output. If any
errors are found, all errors are returned. If validation succeeds, stdout is
exactly "passed". The protocol file is never modified.`,
	RunE: validateProtocol,
}

func init() {
	protocolValidateCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file (required)")
	protocolValidateCmd.MarkFlagRequired("file")
}

type validatedProtocol struct {
	ProjectID   string                     `json:"project_id"`
	ProtocolID  string                     `json:"protocol_id"`
	UserID      string                     `json:"user_id,omitempty"`
	Username    string                     `json:"username,omitempty"`
	Description string                     `json:"description"`
	Timestamp   string                     `json:"timestamp"`
	Summary     validatedProtocolSummary   `json:"summary"`
	Commands    []validatedProtocolCommand `json:"commands"`
}

type validatedProtocolSummary struct {
	Valid                         bool `json:"valid"`
	TotalCommands                 int  `json:"total_commands"`
	Machines                      int  `json:"machines"`
	CommandsRequiringConfirmation int  `json:"commands_requiring_confirmation"`
}

type validatedProtocolCommand struct {
	Name        string                 `json:"name"`
	Params      map[string]interface{} `json:"params"`
	Kwargs      map[string]interface{} `json:"kwargs,omitempty"`
	StepNumber  int                    `json:"step_number"`
	Version     string                 `json:"version,omitempty"`
	MachineID   string                 `json:"machine_id"`
	Description string                 `json:"description"`
	Safety      *puda.CommandSafety    `json:"safety,omitempty"`
	Valid       bool                   `json:"valid"`
	Errors      []string               `json:"errors"`
}

type parameterKind string

const (
	parameterInt    parameterKind = "int"
	parameterFloat  parameterKind = "float"
	parameterString parameterKind = "str"
	parameterBool   parameterKind = "bool"
	parameterDict   parameterKind = "dict"
	parameterList   parameterKind = "list"
)

type parameterType struct {
	Kinds    []parameterKind
	Nullable bool
}

type parsedMachineParam struct {
	Required bool
	Type     parameterType
}

type parsedMachineCommand struct {
	Description string
	Safety      *puda.CommandSafety
	Params      map[string]parsedMachineParam
	ExtraKwargs *parameterType
}

type catalogFetchResult struct {
	machineID string
	catalog   pudanats.MachineCommands
	err       error
}

func validateProtocol(cmd *cobra.Command, args []string) error {
	protocolJSON, err := puda.LoadProtocol(protocolFilePath)
	if err != nil {
		return fmt.Errorf("failed to load protocol file: %w", err)
	}
	var protocolFile puda.ProtocolFile
	if err := json.Unmarshal(protocolJSON, &protocolFile); err != nil {
		return fmt.Errorf("failed to parse protocol JSON: %w", err)
	}

	nc, err := connectMachineNATS()
	if err != nil {
		return err
	}
	defer nc.Close()

	_, validationErrors := validateAndEnrichProtocol(&protocolFile, func(machineID string) (pudanats.MachineCommands, error) {
		return pudanats.GetMachineCommands(nc, machineID)
	})
	if len(validationErrors) > 0 {
		return formatProtocolValidationErrors(validationErrors)
	}
	return writeProtocolValidationSuccess(cmd.OutOrStdout())
}

func writeProtocolValidationSuccess(writer io.Writer) error {
	_, err := fmt.Fprintln(writer, "passed")
	return err
}

// validateAndEnrichProtocol aggregates local structure errors and every live
// catalog error that can still be resolved safely. Error order follows protocol
// order, independent of catalog fetch completion order.
func validateAndEnrichProtocol(protocol *puda.ProtocolFile, fetchCatalog func(string) (pudanats.MachineCommands, error)) (*validatedProtocol, []puda.ValidationError) {
	structuralErrors, _ := puda.ValidateProtocol(protocol)
	machineIDs := resolvableMachineIDs(protocol.Commands)
	catalogs, catalogErrors := fetchMachineCatalogs(machineIDs, fetchCatalog)

	parsedCatalogs := make(map[string]map[string]parsedMachineCommand, len(catalogs))
	for _, machineID := range machineIDs {
		if catalogErrors[machineID] != nil {
			continue
		}
		parsed, err := parseMachineCatalog(catalogs[machineID])
		if err != nil {
			catalogErrors[machineID] = err
			continue
		}
		parsedCatalogs[machineID] = parsed
	}

	liveErrors := make([]puda.ValidationError, 0)
	enrichedCommands := make([]validatedProtocolCommand, 0, len(protocol.Commands))
	confirmationCount := 0
	for index, command := range protocol.Commands {
		if command.MachineID == "" {
			continue
		}
		if catalogErr := catalogErrors[command.MachineID]; catalogErr != nil {
			liveErrors = append(liveErrors, puda.ValidationError{CommandIndex: index, Field: "machine_id", Message: fmt.Sprintf("failed to resolve command catalog for %s: %v", command.MachineID, catalogErr)})
			continue
		}
		if command.Name == "" {
			continue
		}
		parsed, ok := parsedCatalogs[command.MachineID][command.Name]
		if !ok {
			liveErrors = append(liveErrors, puda.ValidationError{CommandIndex: index, Field: "name", Message: fmt.Sprintf("command %q not found for machine", command.Name)})
			continue
		}
		commandErrors := validateCommandParams(index, command, parsed)
		liveErrors = append(liveErrors, commandErrors...)
		if len(commandErrors) > 0 {
			continue
		}

		if parsed.Safety != nil && parsed.Safety.Confirm {
			confirmationCount++
		}
		params := command.Params
		if params == nil {
			params = map[string]interface{}{}
		}
		enrichedCommands = append(enrichedCommands, validatedProtocolCommand{
			Name: command.Name, Params: params, Kwargs: command.Kwargs,
			StepNumber: command.StepNumber, Version: command.Version, MachineID: command.MachineID,
			Description: parsed.Description, Safety: parsed.Safety, Valid: true, Errors: []string{},
		})
	}

	validationErrors := append(structuralErrors, liveErrors...)
	sort.SliceStable(validationErrors, func(left, right int) bool {
		return validationErrors[left].CommandIndex < validationErrors[right].CommandIndex
	})
	if len(validationErrors) > 0 {
		return nil, validationErrors
	}
	return &validatedProtocol{
		ProjectID: protocol.ProjectID, ProtocolID: protocol.ProtocolID, UserID: protocol.UserID,
		Username: protocol.Username, Description: protocol.Description, Timestamp: protocol.Timestamp,
		Summary:  validatedProtocolSummary{Valid: true, TotalCommands: len(enrichedCommands), Machines: len(machineIDs), CommandsRequiringConfirmation: confirmationCount},
		Commands: enrichedCommands,
	}, nil
}

func resolvableMachineIDs(commands []puda.CommandRequest) []string {
	set := make(map[string]struct{})
	for _, command := range commands {
		if command.MachineID != "" {
			set[command.MachineID] = struct{}{}
		}
	}
	ids := make([]string, 0, len(set))
	for id := range set {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func fetchMachineCatalogs(machineIDs []string, fetch func(string) (pudanats.MachineCommands, error)) (map[string]pudanats.MachineCommands, map[string]error) {
	catalogs := make(map[string]pudanats.MachineCommands, len(machineIDs))
	errorsByMachine := make(map[string]error)
	if len(machineIDs) == 0 {
		return catalogs, errorsByMachine
	}

	jobs := make(chan string)
	results := make(chan catalogFetchResult, len(machineIDs))
	workers := machineCatalogWorkerLimit
	if len(machineIDs) < workers {
		workers = len(machineIDs)
	}
	var workersWG sync.WaitGroup
	for range workers {
		workersWG.Add(1)
		go func() {
			defer workersWG.Done()
			for machineID := range jobs {
				catalog, err := fetch(machineID)
				results <- catalogFetchResult{machineID: machineID, catalog: catalog, err: err}
			}
		}()
	}
	go func() {
		for _, machineID := range machineIDs {
			jobs <- machineID
		}
		close(jobs)
		workersWG.Wait()
		close(results)
	}()
	for result := range results {
		if result.err != nil {
			errorsByMachine[result.machineID] = result.err
		} else {
			catalogs[result.machineID] = result.catalog
		}
	}
	return catalogs, errorsByMachine
}

func parseMachineCatalog(catalog pudanats.MachineCommands) (map[string]parsedMachineCommand, error) {
	if catalog.Catalog == nil {
		return nil, fmt.Errorf("catalog field is missing")
	}
	parsed := make(map[string]parsedMachineCommand, len(catalog.Catalog))
	for index, entry := range catalog.Catalog {
		if entry.Name == "" || entry.Signature == "" || !entry.DocPresent || !entry.SafetyPresent {
			return nil, fmt.Errorf("catalog[%d] is missing required name, signature, doc, or safety field", index)
		}
		if _, duplicate := parsed[entry.Name]; duplicate {
			return nil, fmt.Errorf("catalog contains duplicate command %q", entry.Name)
		}
		if entry.Safety != nil && (entry.Safety.Summary == "" || entry.Safety.Hazards == nil || entry.Safety.Confirm == nil) {
			return nil, fmt.Errorf("catalog[%d] has malformed safety metadata", index)
		}
		command, err := parseMachineCommand(entry)
		if err != nil {
			return nil, fmt.Errorf("catalog[%d] command %q: %w", index, entry.Name, err)
		}
		parsed[entry.Name] = command
	}
	return parsed, nil
}

func parseMachineCommand(entry pudanats.MachineCommand) (parsedMachineCommand, error) {
	parameters, err := signatureParameters(entry.Signature)
	if err != nil {
		return parsedMachineCommand{}, err
	}
	parsed := parsedMachineCommand{Params: make(map[string]parsedMachineParam)}
	if entry.Doc != nil {
		parsed.Description = *entry.Doc
	}
	if entry.Safety != nil {
		if entry.Safety.Confirm == nil {
			return parsedMachineCommand{}, fmt.Errorf("catalog safety confirm field is missing")
		}
		parsed.Safety = &puda.CommandSafety{
			Summary: entry.Safety.Summary, Hazards: entry.Safety.Hazards,
			Requires: optionalStringValue(entry.Safety.Requires), ForbiddenWhen: optionalStringValue(entry.Safety.ForbiddenWhen),
			Confirm: *entry.Safety.Confirm,
		}
	}

	for _, rawParameter := range splitTopLevel(parameters) {
		parameter := strings.TrimSpace(rawParameter)
		if parameter == "" || parameter == "self" || parameter == "cls" || parameter == "*" {
			continue
		}
		if parameter == "/" {
			return parsedMachineCommand{}, fmt.Errorf("positional-only signatures are unsupported because edge dispatch is kwargs-only")
		}
		if strings.HasPrefix(parameter, "**") {
			nameAndType := strings.TrimSpace(strings.TrimPrefix(parameter, "**"))
			colon := indexTopLevel(nameAndType, ':')
			if colon < 0 {
				return parsedMachineCommand{}, fmt.Errorf("unsupported unannotated **kwargs parameter")
			}
			typeSpec, err := parseParameterType(nameAndType[colon+1:])
			if err != nil {
				return parsedMachineCommand{}, err
			}
			parsed.ExtraKwargs = &typeSpec
			continue
		}
		if strings.HasPrefix(parameter, "*") {
			return parsedMachineCommand{}, fmt.Errorf("variadic positional parameters are unsupported because edge dispatch is kwargs-only")
		}

		required := indexTopLevel(parameter, '=') < 0
		declaration := parameter
		if equals := indexTopLevel(declaration, '='); equals >= 0 {
			declaration = declaration[:equals]
		}
		colon := indexTopLevel(declaration, ':')
		if colon < 0 {
			return parsedMachineCommand{}, fmt.Errorf("parameter %q has no type annotation", strings.TrimSpace(declaration))
		}
		name := strings.TrimSpace(declaration[:colon])
		if name == "" {
			return parsedMachineCommand{}, fmt.Errorf("invalid empty parameter name")
		}
		if _, duplicate := parsed.Params[name]; duplicate {
			return parsedMachineCommand{}, fmt.Errorf("duplicate parameter %q in signature", name)
		}
		typeSpec, err := parseParameterType(declaration[colon+1:])
		if err != nil {
			return parsedMachineCommand{}, fmt.Errorf("parameter %q: %w", name, err)
		}
		parsed.Params[name] = parsedMachineParam{Required: required, Type: typeSpec}
	}
	return parsed, nil
}

func signatureParameters(signature string) (string, error) {
	open := strings.Index(signature, "(")
	if open < 0 {
		return "", fmt.Errorf("invalid signature %q: missing opening parenthesis", signature)
	}
	depth := 0
	var quote byte
	escaped := false
	for index := open; index < len(signature); index++ {
		character := signature[index]
		if quote != 0 {
			if escaped {
				escaped = false
			} else if character == '\\' {
				escaped = true
			} else if character == quote {
				quote = 0
			}
			continue
		}
		switch character {
		case '\'', '"':
			quote = character
		case '(':
			depth++
		case ')':
			depth--
			if depth == 0 {
				return signature[open+1 : index], nil
			}
		}
	}
	return "", fmt.Errorf("invalid signature %q: unbalanced parentheses", signature)
}

func parseParameterType(annotation string) (parameterType, error) {
	annotation = strings.TrimSpace(annotation)
	if len(annotation) >= 2 && ((annotation[0] == '\'' && annotation[len(annotation)-1] == '\'') || (annotation[0] == '"' && annotation[len(annotation)-1] == '"')) {
		annotation = strings.TrimSpace(annotation[1 : len(annotation)-1])
	}
	annotation = strings.TrimPrefix(annotation, "typing.")
	if strings.HasPrefix(annotation, "Optional[") && strings.HasSuffix(annotation, "]") {
		result, err := parseParameterType(annotation[len("Optional[") : len(annotation)-1])
		result.Nullable = true
		return result, err
	}
	if strings.HasPrefix(annotation, "Union[") && strings.HasSuffix(annotation, "]") {
		return parseTypeUnion(splitTopLevel(annotation[len("Union[") : len(annotation)-1]))
	}
	if parts := splitTopLevelPipes(annotation); len(parts) > 1 {
		return parseTypeUnion(parts)
	}
	if annotation == "None" || annotation == "NoneType" {
		return parameterType{Nullable: true}, nil
	}
	kind, ok := map[string]parameterKind{
		"int": parameterInt, "float": parameterFloat, "str": parameterString,
		"bool": parameterBool, "dict": parameterDict, "list": parameterList,
	}[annotation]
	if !ok {
		return parameterType{}, fmt.Errorf("unsupported annotation %q", annotation)
	}
	return parameterType{Kinds: []parameterKind{kind}}, nil
}

func parseTypeUnion(parts []string) (parameterType, error) {
	result := parameterType{}
	seen := make(map[parameterKind]struct{})
	for _, part := range parts {
		member, err := parseParameterType(part)
		if err != nil {
			return parameterType{}, err
		}
		result.Nullable = result.Nullable || member.Nullable
		for _, kind := range member.Kinds {
			if _, ok := seen[kind]; !ok {
				seen[kind] = struct{}{}
				result.Kinds = append(result.Kinds, kind)
			}
		}
	}
	return result, nil
}

func splitTopLevelPipes(value string) []string {
	parts := []string{}
	start, depth := 0, 0
	for index, character := range value {
		switch character {
		case '[', '(', '{':
			depth++
		case ']', ')', '}':
			depth--
		case '|':
			if depth == 0 {
				parts = append(parts, value[start:index])
				start = index + 1
			}
		}
	}
	return append(parts, value[start:])
}

func validateCommandParams(commandIndex int, command puda.CommandRequest, parsed parsedMachineCommand) []puda.ValidationError {
	errors := make([]puda.ValidationError, 0)
	provided := make(map[string]struct{}, len(command.Params)+len(command.Kwargs))
	for _, name := range sortedParameterNames(command.Params) {
		provided[name] = struct{}{}
		errors = append(errors, validateParameterValue(commandIndex, "params."+name, command.Name, name, command.Params[name], parsed)...)
	}
	for _, name := range sortedParameterNames(command.Kwargs) {
		if _, duplicate := provided[name]; duplicate {
			errors = append(errors, puda.ValidationError{CommandIndex: commandIndex, Field: "kwargs." + name, Message: fmt.Sprintf("parameter %s is present in both params and kwargs", name)})
			continue
		}
		provided[name] = struct{}{}
		errors = append(errors, validateParameterValue(commandIndex, "kwargs."+name, command.Name, name, command.Kwargs[name], parsed)...)
	}

	names := make([]string, 0, len(parsed.Params))
	for name := range parsed.Params {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		if parsed.Params[name].Required {
			if _, ok := provided[name]; !ok {
				errors = append(errors, puda.ValidationError{CommandIndex: commandIndex, Field: "params." + name, Message: fmt.Sprintf("required parameter %s is missing", name)})
			}
		}
	}
	return errors
}

func validateParameterValue(commandIndex int, field, commandName, name string, value interface{}, parsed parsedMachineCommand) []puda.ValidationError {
	typeSpec, accepted := parsed.Params[name]
	var expected parameterType
	if accepted {
		expected = typeSpec.Type
	} else if parsed.ExtraKwargs != nil {
		expected = *parsed.ExtraKwargs
	} else {
		return []puda.ValidationError{{CommandIndex: commandIndex, Field: field, Message: fmt.Sprintf("command %s does not accept parameter %s", commandName, name)}}
	}
	if value == nil {
		if expected.Nullable {
			return nil
		}
		return []puda.ValidationError{{CommandIndex: commandIndex, Field: field, Message: fmt.Sprintf("parameter %s does not allow null", name)}}
	}
	for _, kind := range expected.Kinds {
		if valueMatchesParameterKind(value, kind) {
			return nil
		}
	}
	return []puda.ValidationError{{CommandIndex: commandIndex, Field: field, Message: fmt.Sprintf("parameter %s must match annotation %s", name, formatParameterType(expected))}}
}

func valueMatchesParameterKind(value interface{}, kind parameterKind) bool {
	switch kind {
	case parameterInt:
		number, ok := value.(float64)
		return ok && !math.IsNaN(number) && !math.IsInf(number, 0) && math.Trunc(number) == number
	case parameterFloat:
		_, ok := value.(float64)
		return ok
	case parameterString:
		_, ok := value.(string)
		return ok
	case parameterBool:
		_, ok := value.(bool)
		return ok
	case parameterDict:
		_, ok := value.(map[string]interface{})
		return ok
	case parameterList:
		_, ok := value.([]interface{})
		return ok
	default:
		return false
	}
}

func formatParameterType(value parameterType) string {
	parts := make([]string, 0, len(value.Kinds)+1)
	for _, kind := range value.Kinds {
		parts = append(parts, string(kind))
	}
	if value.Nullable {
		parts = append(parts, "None")
	}
	return strings.Join(parts, " | ")
}

func optionalStringValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func sortedParameterNames(parameters map[string]interface{}) []string {
	names := make([]string, 0, len(parameters))
	for name := range parameters {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func splitTopLevel(value string) []string {
	parts := []string{}
	start, depth := 0, 0
	var quote rune
	escaped := false
	for index, character := range value {
		if quote != 0 {
			if escaped {
				escaped = false
			} else if character == '\\' {
				escaped = true
			} else if character == quote {
				quote = 0
			}
			continue
		}
		switch character {
		case '\'', '"':
			quote = character
		case '(', '[', '{':
			depth++
		case ')', ']', '}':
			depth--
		case ',':
			if depth == 0 {
				parts = append(parts, value[start:index])
				start = index + 1
			}
		}
	}
	return append(parts, value[start:])
}

func indexTopLevel(value string, target rune) int {
	depth := 0
	var quote rune
	escaped := false
	for index, character := range value {
		if quote != 0 {
			if escaped {
				escaped = false
			} else if character == '\\' {
				escaped = true
			} else if character == quote {
				quote = 0
			}
			continue
		}
		switch character {
		case '\'', '"':
			quote = character
		case '(', '[', '{':
			depth++
		case ')', ']', '}':
			depth--
		default:
			if character == target && depth == 0 {
				return index
			}
		}
	}
	return -1
}

func formatProtocolValidationErrors(validationErrors []puda.ValidationError) error {
	var builder strings.Builder
	fmt.Fprintf(&builder, "protocol validation failed with %d error(s):", len(validationErrors))
	for _, validationError := range validationErrors {
		fmt.Fprintf(&builder, "\ncommands[%d] %s: %s", validationError.CommandIndex, validationError.Field, validationError.Message)
	}
	return fmt.Errorf("%s", builder.String())
}
