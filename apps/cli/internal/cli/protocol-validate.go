package cli

import (
	"encoding/json"
	"fmt"
	"io"
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
	Long: `Validate a protocol JSON file against the advertised commands it uses.

Only commands named in the protocol are parsed from each machine catalog.
Unused catalog entries are ignored, so an unrelated signature cannot fail
validation. Unannotated parameters, *args, and **kwargs are accepted without
a type check.

wait is a CLI builtin: it is not looked up in a machine catalog and does not
require machine_id. params.seconds must be a number >= 0.

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
	usedNames := usedMachineCommandNames(protocol.Commands)
	catalogs, catalogErrors := fetchMachineCatalogs(machineIDs, fetchCatalog)

	parsedCatalogs := make(map[string]map[string]parsedMachineCommand, len(catalogs))
	commandCatalogErrors := make(map[string]map[string]error, len(catalogs))
	for _, machineID := range machineIDs {
		if catalogErrors[machineID] != nil {
			continue
		}
		parsed, commandErrors, err := parseUsedMachineCommands(catalogs[machineID], usedNames[machineID])
		if err != nil {
			catalogErrors[machineID] = err
			continue
		}
		parsedCatalogs[machineID] = parsed
		if len(commandErrors) > 0 {
			commandCatalogErrors[machineID] = commandErrors
		}
	}

	liveErrors := make([]puda.ValidationError, 0)
	enrichedCommands := make([]validatedProtocolCommand, 0, len(protocol.Commands))
	confirmationCount := 0
	for index, command := range protocol.Commands {
		if puda.IsWaitCommand(command) {
			if _, err := puda.ParseWaitDuration(command.Params); err != nil {
				continue
			}
			params := command.Params
			if params == nil {
				params = map[string]interface{}{}
			}
			enrichedCommands = append(enrichedCommands, validatedProtocolCommand{
				Name: command.Name, Params: params, Kwargs: command.Kwargs,
				StepNumber: command.StepNumber, Version: command.Version, MachineID: command.MachineID,
				Description: "Wait locally in the CLI without sending a machine command.", Valid: true, Errors: []string{},
			})
			continue
		}
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
		if commandErr := commandCatalogErrors[command.MachineID][command.Name]; commandErr != nil {
			liveErrors = append(liveErrors, puda.ValidationError{CommandIndex: index, Field: "name", Message: fmt.Sprintf("failed to parse advertised command %q: %v", command.Name, commandErr)})
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

func usedMachineCommandNames(commands []puda.CommandRequest) map[string]map[string]struct{} {
	used := make(map[string]map[string]struct{})
	for _, command := range commands {
		if puda.IsWaitCommand(command) || command.MachineID == "" || command.Name == "" {
			continue
		}
		names := used[command.MachineID]
		if names == nil {
			names = make(map[string]struct{})
			used[command.MachineID] = names
		}
		names[command.Name] = struct{}{}
	}
	return used
}

func resolvableMachineIDs(commands []puda.CommandRequest) []string {
	set := make(map[string]struct{})
	for _, command := range commands {
		if puda.IsWaitCommand(command) {
			continue
		}
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

func parseUsedMachineCommands(catalog pudanats.MachineCommands, usedNames map[string]struct{}) (map[string]parsedMachineCommand, map[string]error, error) {
	if catalog.Catalog == nil {
		return nil, nil, fmt.Errorf("catalog field is missing")
	}
	parsed := make(map[string]parsedMachineCommand, len(usedNames))
	commandErrors := make(map[string]error)
	seen := make(map[string]int, len(usedNames))
	for index, entry := range catalog.Catalog {
		if _, used := usedNames[entry.Name]; !used {
			continue
		}
		if previous, duplicate := seen[entry.Name]; duplicate {
			commandErrors[entry.Name] = fmt.Errorf("catalog contains duplicate command %q (catalog[%d] and catalog[%d])", entry.Name, previous, index)
			delete(parsed, entry.Name)
			continue
		}
		seen[entry.Name] = index
		if entry.Name == "" || entry.Signature == "" || !entry.DocPresent || !entry.SafetyPresent {
			commandErrors[entry.Name] = fmt.Errorf("catalog[%d] is missing required name, signature, doc, or safety field", index)
			continue
		}
		if entry.Safety != nil && (entry.Safety.Summary == "" || entry.Safety.Hazards == nil || entry.Safety.Confirm == nil) {
			commandErrors[entry.Name] = fmt.Errorf("catalog[%d] has malformed safety metadata", index)
			continue
		}
		command, err := parseMachineCommand(entry)
		if err != nil {
			commandErrors[entry.Name] = fmt.Errorf("catalog[%d] command %q: %w", index, entry.Name, err)
			continue
		}
		parsed[entry.Name] = command
	}
	return parsed, commandErrors, nil
}

func parseMachineCommand(entry pudanats.MachineCommand) (parsedMachineCommand, error) {
	parameters, err := signatureParameters(entry.Signature)
	if err != nil {
		return parsedMachineCommand{}, err
	}
	catalogSchemas, err := catalogParameterSchemas(entry)
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
			name, annotation, hasAnnotation := splitNameAndAnnotation(nameAndType)
			if name == "" {
				return parsedMachineCommand{}, fmt.Errorf("invalid empty parameter name")
			}
			typeSpec, err := resolveParameterSchema(name, annotation, hasAnnotation, catalogSchemas)
			if err != nil {
				return parsedMachineCommand{}, fmt.Errorf("parameter %q: %w", name, err)
			}
			parsed.ExtraKwargs = &typeSpec
			continue
		}
		if strings.HasPrefix(parameter, "*") {
			continue
		}

		required := indexTopLevel(parameter, '=') < 0
		declaration := parameter
		if equals := indexTopLevel(declaration, '='); equals >= 0 {
			declaration = declaration[:equals]
		}
		name, annotation, hasAnnotation := splitNameAndAnnotation(declaration)
		if name == "" {
			return parsedMachineCommand{}, fmt.Errorf("invalid empty parameter name")
		}
		if _, duplicate := parsed.Params[name]; duplicate {
			return parsedMachineCommand{}, fmt.Errorf("duplicate parameter %q in signature", name)
		}
		typeSpec, err := resolveParameterSchema(name, annotation, hasAnnotation, catalogSchemas)
		if err != nil {
			return parsedMachineCommand{}, fmt.Errorf("parameter %q: %w", name, err)
		}
		parsed.Params[name] = parsedMachineParam{Required: required, Type: typeSpec}
	}
	return parsed, nil
}

func catalogParameterSchemas(entry pudanats.MachineCommand) (map[string]parameterType, error) {
	schemas := make(map[string]parameterType, len(entry.Parameters))
	for name, spec := range entry.Parameters {
		if len(spec.Schema) == 0 {
			continue
		}
		schema, err := schemaFromJSON(spec.Schema)
		if err != nil {
			return nil, fmt.Errorf("parameter %q: %w", name, err)
		}
		schemas[name] = schema
	}
	return schemas, nil
}

func splitNameAndAnnotation(declaration string) (string, string, bool) {
	declaration = strings.TrimSpace(declaration)
	colon := indexTopLevel(declaration, ':')
	if colon < 0 {
		return declaration, "", false
	}
	return strings.TrimSpace(declaration[:colon]), declaration[colon+1:], true
}

func resolveParameterSchema(name, annotation string, hasAnnotation bool, catalogSchemas map[string]parameterType) (parameterType, error) {
	if schema, ok := catalogSchemas[name]; ok {
		return schema, nil
	}
	if !hasAnnotation {
		return unconstrainedType(), nil
	}
	return parseParameterType(annotation)
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
		if expected.Nullable || expected.Kind == parameterNull || expected.Kind == parameterAny {
			return nil
		}
		return []puda.ValidationError{{CommandIndex: commandIndex, Field: field, Message: fmt.Sprintf("parameter %s does not allow null", name)}}
	}
	if valueMatchesSchema(value, expected) {
		return nil
	}
	return []puda.ValidationError{{CommandIndex: commandIndex, Field: field, Message: fmt.Sprintf("parameter %s must match annotation %s", name, formatParameterType(expected))}}
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
		if character == target && depth == 0 {
			return index
		}
		switch character {
		case '\'', '"':
			quote = character
		case '(', '[', '{':
			depth++
		case ')', ']', '}':
			depth--
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
