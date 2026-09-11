package cli

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
)

// JSON-compatible primitive kinds. Catalog schemas must be expressible in any
// language; Python-only typing forms are normalized to these by an SDK or
// rejected by the signature parser.
type parameterKind string

const (
	parameterInt    parameterKind = "int"
	parameterFloat  parameterKind = "float"
	parameterString parameterKind = "str"
	parameterBool   parameterKind = "bool"
	parameterBytes  parameterKind = "bytes"
	parameterNull   parameterKind = "null"
	parameterAny    parameterKind = "any"
	parameterDict   parameterKind = "dict"
	parameterList   parameterKind = "list"
	parameterUnion  parameterKind = "union"
)

const supportedAnnotationSuggestion = "use a JSON-compatible primitive (str, int, float, bool, bytes, null, dict, list, optional/nullable, or a union of those) or emit a structured catalog schema"

type parameterType struct {
	Kind     parameterKind   `json:"kind,omitempty"`
	Nullable bool            `json:"nullable,omitempty"`
	Values   *parameterType  `json:"values,omitempty"`
	Items    *parameterType  `json:"items,omitempty"`
	Members  []parameterType `json:"members,omitempty"`
}

func parseParameterType(annotation string) (parameterType, error) {
	schema, err := parseAnnotation(annotation)
	if err != nil {
		return parameterType{}, err
	}
	return canonicalize(schema), nil
}

func schemaFromJSON(raw json.RawMessage) (parameterType, error) {
	var schema parameterType
	if err := json.Unmarshal(raw, &schema); err != nil {
		return parameterType{}, fmt.Errorf("invalid parameter schema: %w", err)
	}
	if schema.Kind == "" && len(schema.Members) == 0 && !schema.Nullable {
		return parameterType{}, fmt.Errorf("invalid parameter schema: missing kind")
	}
	return canonicalize(schema), nil
}

func parseAnnotation(annotation string) (parameterType, error) {
	original := strings.TrimSpace(annotation)
	annotation = unwrapAnnotationQuotes(original)
	annotation = stripModulePrefixes(annotation)
	if annotation == "" {
		return parameterType{}, annotationError(original, "", nil, "")
	}

	if parts := splitTopLevelPipes(annotation); len(parts) > 1 {
		return parseTypeUnion(parts)
	}

	if origin, args, ok := splitGeneric(annotation); ok {
		return parseOrigin(original, origin, args)
	}
	return parseOrigin(original, annotation, nil)
}

func parseOrigin(original, origin string, args []string) (parameterType, error) {
	origin = stripModulePrefixes(strings.TrimSpace(origin))
	switch origin {
	case "Optional":
		if len(args) != 1 {
			return parameterType{}, annotationError(original, origin, args, "Optional requires one type argument")
		}
		inner, err := parseArg(original, origin, args, 0)
		if err != nil {
			return parameterType{}, err
		}
		inner.Nullable = true
		return inner, nil
	case "Union":
		if len(args) == 0 {
			return parameterType{}, annotationError(original, origin, args, "Union requires type arguments")
		}
		return parseTypeUnion(args)
	case "Any", "any":
		if len(args) != 0 {
			return parameterType{}, annotationError(original, origin, args, "")
		}
		return parameterType{Kind: parameterAny}, nil
	case "None", "NoneType", "null":
		if len(args) != 0 {
			return parameterType{}, annotationError(original, origin, args, "")
		}
		return parameterType{Kind: parameterNull}, nil
	case "str", "string":
		return primitiveOrigin(original, origin, args, parameterString)
	case "int", "integer":
		return primitiveOrigin(original, origin, args, parameterInt)
	case "float", "number":
		return primitiveOrigin(original, origin, args, parameterFloat)
	case "bool", "boolean":
		return primitiveOrigin(original, origin, args, parameterBool)
	case "bytes":
		return primitiveOrigin(original, origin, args, parameterBytes)
	case "dict", "Dict", "object":
		return parseMappingOrigin(original, origin, args)
	case "list", "List", "array":
		return parseSequenceOrigin(original, origin, args)
	default:
		return parameterType{}, annotationError(original, origin, args, "")
	}
}

func primitiveOrigin(original, origin string, args []string, kind parameterKind) (parameterType, error) {
	if len(args) != 0 {
		return parameterType{}, annotationError(original, origin, args, "")
	}
	return parameterType{Kind: kind}, nil
}

func parseArg(original, origin string, args []string, index int) (parameterType, error) {
	parsed, err := parseAnnotation(args[index])
	if err != nil {
		return parameterType{}, annotationError(original, origin, args, "")
	}
	return parsed, nil
}

func parseMappingOrigin(original, origin string, args []string) (parameterType, error) {
	switch len(args) {
	case 0:
		return parameterType{Kind: parameterDict}, nil
	case 2:
		key, err := parseArg(original, origin, args, 0)
		if err != nil {
			return parameterType{}, err
		}
		if !isJSONObjectKey(key) {
			return parameterType{}, annotationError(original, origin, args, "object keys must be str")
		}
		values, err := parseArg(original, origin, args, 1)
		if err != nil {
			return parameterType{}, err
		}
		return parameterType{Kind: parameterDict, Values: &values}, nil
	default:
		return parameterType{}, annotationError(original, origin, args, "objects require zero or two type arguments")
	}
}

func parseSequenceOrigin(original, origin string, args []string) (parameterType, error) {
	switch len(args) {
	case 0:
		return parameterType{Kind: parameterList}, nil
	case 1:
		items, err := parseArg(original, origin, args, 0)
		if err != nil {
			return parameterType{}, err
		}
		return parameterType{Kind: parameterList, Items: &items}, nil
	default:
		return parameterType{}, annotationError(original, origin, args, "arrays require zero or one type argument")
	}
}

func parseTypeUnion(parts []string) (parameterType, error) {
	members := make([]parameterType, 0, len(parts))
	for _, part := range parts {
		member, err := parseAnnotation(strings.TrimSpace(part))
		if err != nil {
			return parameterType{}, err
		}
		members = append(members, member)
	}
	return parameterType{Kind: parameterUnion, Members: members}, nil
}

func isJSONObjectKey(schema parameterType) bool {
	canonical := canonicalize(schema)
	return canonical.Kind == parameterString && !canonical.Nullable && canonical.Values == nil && canonical.Items == nil && len(canonical.Members) == 0
}

func canonicalize(schema parameterType) parameterType {
	if schema.Values != nil {
		canonical := canonicalize(*schema.Values)
		schema.Values = &canonical
	}
	if schema.Items != nil {
		canonical := canonicalize(*schema.Items)
		schema.Items = &canonical
	}
	if schema.Kind == parameterUnion || len(schema.Members) > 0 {
		nullable, members := flattenUnion(schema)
		return collapseUnion(nullable, members)
	}
	if schema.Kind == parameterAny {
		schema.Nullable = false
	}
	if len(schema.Members) == 0 {
		schema.Members = nil
	}
	return schema
}

func flattenUnion(schema parameterType) (bool, []parameterType) {
	nullable := schema.Nullable
	if schema.Kind == parameterNull {
		return true, nil
	}
	if schema.Kind != parameterUnion && len(schema.Members) == 0 {
		member := schema
		member.Nullable = false
		if member.Kind == parameterAny {
			return nullable, []parameterType{member}
		}
		return nullable, []parameterType{canonicalize(member)}
	}
	members := make([]parameterType, 0, len(schema.Members))
	for _, member := range schema.Members {
		innerNullable, inner := flattenUnion(member)
		nullable = nullable || innerNullable
		members = append(members, inner...)
	}
	return nullable, members
}

func collapseUnion(nullable bool, members []parameterType) parameterType {
	deduped := make([]parameterType, 0, len(members))
	seen := make(map[string]struct{}, len(members))
	for _, member := range members {
		member.Nullable = false
		if member.Kind == parameterAny {
			return parameterType{Kind: parameterAny}
		}
		key := schemaSortKey(member)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		deduped = append(deduped, member)
	}
	sort.Slice(deduped, func(i, j int) bool { return schemaSortKey(deduped[i]) < schemaSortKey(deduped[j]) })
	if len(deduped) == 0 {
		if nullable {
			return parameterType{Kind: parameterNull}
		}
		return parameterType{}
	}
	if len(deduped) == 1 {
		result := deduped[0]
		if nullable && result.Kind != parameterAny && result.Kind != parameterNull {
			result.Nullable = true
		}
		return result
	}
	return parameterType{Kind: parameterUnion, Nullable: nullable, Members: deduped}
}

func schemaSortKey(schema parameterType) string {
	encoded, err := json.Marshal(schema)
	if err != nil {
		return string(schema.Kind)
	}
	return string(encoded)
}

func valueMatchesSchema(value interface{}, schema parameterType) bool {
	if value == nil {
		return schema.Nullable || schema.Kind == parameterNull || schema.Kind == parameterAny
	}
	switch schema.Kind {
	case parameterUnion:
		for _, member := range schema.Members {
			if valueMatchesSchema(value, member) {
				return true
			}
		}
		return false
	case parameterAny:
		return true
	case parameterNull:
		return false
	case parameterInt:
		number, ok := value.(float64)
		return ok && !math.IsNaN(number) && !math.IsInf(number, 0) && math.Trunc(number) == number
	case parameterFloat:
		_, ok := value.(float64)
		return ok
	case parameterString, parameterBytes:
		_, ok := value.(string)
		return ok
	case parameterBool:
		_, ok := value.(bool)
		return ok
	case parameterDict:
		object, ok := value.(map[string]interface{})
		if !ok {
			return false
		}
		if schema.Values == nil {
			return true
		}
		for _, item := range object {
			if !valueMatchesSchema(item, *schema.Values) {
				return false
			}
		}
		return true
	case parameterList:
		items, ok := value.([]interface{})
		if !ok {
			return false
		}
		if schema.Items == nil {
			return true
		}
		for _, item := range items {
			if !valueMatchesSchema(item, *schema.Items) {
				return false
			}
		}
		return true
	default:
		return false
	}
}

func formatParameterType(schema parameterType) string {
	core := formatParameterTypeCore(schema)
	if schema.Nullable && schema.Kind != parameterNull && schema.Kind != parameterAny {
		if core == "" {
			return "null"
		}
		return core + " | null"
	}
	return core
}

func formatParameterTypeCore(schema parameterType) string {
	switch schema.Kind {
	case parameterDict:
		if schema.Values == nil {
			return "dict"
		}
		return "dict[str, " + formatParameterType(*schema.Values) + "]"
	case parameterList:
		if schema.Items == nil {
			return "list"
		}
		return "list[" + formatParameterType(*schema.Items) + "]"
	case parameterUnion:
		parts := make([]string, 0, len(schema.Members)+1)
		for _, member := range schema.Members {
			parts = append(parts, formatParameterType(member))
		}
		if schema.Nullable {
			parts = append(parts, "null")
		}
		return strings.Join(parts, " | ")
	case parameterNull:
		return "null"
	default:
		return string(schema.Kind)
	}
}

func unwrapAnnotationQuotes(annotation string) string {
	annotation = strings.TrimSpace(annotation)
	if len(annotation) >= 2 && ((annotation[0] == '\'' && annotation[len(annotation)-1] == '\'') || (annotation[0] == '"' && annotation[len(annotation)-1] == '"')) {
		return strings.TrimSpace(annotation[1 : len(annotation)-1])
	}
	return annotation
}

func stripModulePrefixes(annotation string) string {
	for {
		next := annotation
		for _, prefix := range []string{"typing.", "collections.abc.", "collections.", "builtins."} {
			next = strings.TrimPrefix(next, prefix)
		}
		if next == annotation {
			return annotation
		}
		annotation = next
	}
}

func splitGeneric(annotation string) (string, []string, bool) {
	open := indexTopLevel(annotation, '[')
	if open < 0 || !strings.HasSuffix(annotation, "]") {
		return annotation, nil, false
	}
	origin := strings.TrimSpace(annotation[:open])
	if origin == "" {
		return annotation, nil, false
	}
	inner := annotation[open+1 : len(annotation)-1]
	return origin, trimAnnotationParts(splitTopLevel(inner)), true
}

func trimAnnotationParts(parts []string) []string {
	trimmed := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		trimmed = append(trimmed, part)
	}
	return trimmed
}

func annotationError(original, origin string, args []string, detail string) error {
	var builder strings.Builder
	fmt.Fprintf(&builder, "unsupported annotation %q", original)
	if origin != "" || len(args) > 0 {
		fmt.Fprintf(&builder, " (origin=%s, args=%s)", origin, formatArgList(args))
	}
	if detail != "" {
		fmt.Fprintf(&builder, ": %s", detail)
	}
	fmt.Fprintf(&builder, "; %s", supportedAnnotationSuggestion)
	return fmt.Errorf("%s", builder.String())
}

func formatArgList(args []string) string {
	if len(args) == 0 {
		return "[]"
	}
	return "[" + strings.Join(args, ", ") + "]"
}
