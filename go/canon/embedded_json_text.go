package canon

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
)

const (
	pendingGeneratedConverterUUID  = "urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR"
	pendingGeneratedConverterToken = "PENDIENTE-GENERACION-CONVERTIDOR"
)

// NormalizeEmbeddedJSONText compacts structured JSON payloads carried inside
// entry.Text and resolves the historical placeholder top-level id when the
// payload is a JSON object authored by the canon session flow.
//
// The normalization is conservative:
//   - only candidates that look like JSON objects/arrays are considered
//   - key order is preserved via json.Compact on the original byte stream
//   - invalid JSON escapes are repaired by doubling the offending backslash,
//     preserving the literal character sequence instead of deleting content
func NormalizeEmbeddedJSONText(entry *CanonEntry) ([]string, error) {
	if entry == nil || entry.Text == nil {
		return nil, nil
	}

	normalized, actions, changed, err := normalizeEmbeddedJSONTextValue(*entry.Text, *entry)
	if err != nil {
		return nil, err
	}
	if changed {
		entry.Text = &normalized
	}
	return actions, nil
}

func normalizeEmbeddedJSONTextValue(raw string, entry CanonEntry) (string, []string, bool, error) {
	if !shouldNormalizeEmbeddedJSON(raw, entry) {
		return raw, nil, false, nil
	}

	trimmed := strings.TrimSpace(raw)
	working := trimmed
	var actions []string

	working, repairActions := repairEmbeddedJSONShape(working)
	actions = append(actions, repairActions...)

	if !json.Valid([]byte(working)) {
		return raw, nil, false, fmt.Errorf("embedded JSON text is invalid and could not be repaired")
	}

	var compacted bytes.Buffer
	if err := json.Compact(&compacted, []byte(working)); err != nil {
		return raw, nil, false, fmt.Errorf("compact embedded JSON text: %w", err)
	}

	normalized := compacted.String()
	if normalized != working {
		actions = append(actions, "compacted embedded JSON text")
	}

	resolvedID, err := computeResolvedEmbeddedTextID(entry)
	if err != nil {
		return raw, nil, false, fmt.Errorf("compute embedded JSON id: %w", err)
	}
	if resolvedID != "" && strings.HasPrefix(normalized, "{") {
		rewritten, changed, err := replaceTopLevelJSONObjectIDPlaceholder(normalized, resolvedID)
		if err != nil {
			return raw, nil, false, fmt.Errorf("rewrite embedded JSON id: %w", err)
		}
		if changed {
			normalized = rewritten
			actions = append(actions, "resolved embedded JSON id from canonical identity")
		}
	}

	if normalized == raw {
		return raw, actions, false, nil
	}
	return normalized, actions, true, nil
}

func shouldNormalizeEmbeddedJSON(raw string, entry CanonEntry) bool {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return false
	}
	switch trimmed[0] {
	case '{', '[':
	default:
		return false
	}

	if entry.ContentType == ContentTypeJSON {
		return true
	}
	if entry.SourceType != nil && strings.EqualFold(strings.TrimSpace(*entry.SourceType), ContentTypeJSON) {
		return true
	}
	return json.Valid([]byte(trimmed))
}

func computeResolvedEmbeddedTextID(entry CanonEntry) (string, error) {
	key := entry.Key
	if key == "" && entry.Title != "" {
		key = KeyOf(entry.Title)
	}
	if key == "" {
		return "", nil
	}
	return ComputeNodeUUID(string(key))
}

func repairInvalidEmbeddedJSONEscapes(raw string) string {
	var out strings.Builder
	out.Grow(len(raw) + 16)

	inString := false
	for i := 0; i < len(raw); {
		ch := raw[i]

		if !inString {
			out.WriteByte(ch)
			if ch == '"' {
				inString = true
			}
			i++
			continue
		}

		switch ch {
		case '"':
			inString = false
			out.WriteByte(ch)
			i++
		case '\\':
			if i+1 < len(raw) {
				next := raw[i+1]
				if next == 'u' && i+5 < len(raw) && isHexQuartet(raw[i+2:i+6]) {
					out.WriteString(raw[i : i+6])
					i += 6
					continue
				}
				if isStandardJSONEscape(next) {
					out.WriteByte('\\')
					out.WriteByte(next)
					i += 2
					continue
				}
			}
			// Preserve the literal backslash by escaping it instead of dropping it.
			out.WriteString(`\\`)
			i++
		default:
			out.WriteByte(ch)
			i++
		}
	}

	return out.String()
}

func repairEmbeddedJSONShape(raw string) (string, []string) {
	if json.Valid([]byte(raw)) {
		return raw, nil
	}

	working := raw
	var actions []string
	recorded := map[string]bool{}

	for pass := 0; pass < 3; pass++ {
		if json.Valid([]byte(working)) {
			break
		}

		mutated := false
		repairedEscapes := repairInvalidEmbeddedJSONEscapes(working)
		if repairedEscapes != working {
			working = repairedEscapes
			mutated = true
			if !recorded["escapes"] {
				actions = append(actions, "repaired invalid embedded JSON escapes")
				recorded["escapes"] = true
			}
		}

		if json.Valid([]byte(working)) {
			break
		}

		repairedCommas := repairMissingEmbeddedJSONArrayCommas(working)
		if repairedCommas != working {
			working = repairedCommas
			mutated = true
			if !recorded["array-commas"] {
				actions = append(actions, "repaired missing embedded JSON commas between array values")
				recorded["array-commas"] = true
			}
		}

		if !mutated {
			break
		}
	}

	return working, actions
}

func repairMissingEmbeddedJSONArrayCommas(raw string) string {
	if raw == "" {
		return raw
	}

	var out strings.Builder
	out.Grow(len(raw) + 16)

	stack := make([]byte, 0, 8)
	inString := false
	escaped := false

	for i := 0; i < len(raw); i++ {
		ch := raw[i]
		out.WriteByte(ch)

		if inString {
			if escaped {
				escaped = false
				continue
			}
			switch ch {
			case '\\':
				escaped = true
			case '"':
				inString = false
			}
			continue
		}

		switch ch {
		case '"':
			inString = true
		case '{', '[':
			stack = append(stack, ch)
		case '}':
			if len(stack) > 0 && stack[len(stack)-1] == '{' {
				stack = stack[:len(stack)-1]
			}
			if insideJSONArray(stack) && nextJSONArrayValueNeedsComma(raw, i+1) {
				out.WriteByte(',')
			}
		case ']':
			if len(stack) > 0 && stack[len(stack)-1] == '[' {
				stack = stack[:len(stack)-1]
			}
			if insideJSONArray(stack) && nextJSONArrayValueNeedsComma(raw, i+1) {
				out.WriteByte(',')
			}
		}
	}

	return out.String()
}

func insideJSONArray(stack []byte) bool {
	return len(stack) > 0 && stack[len(stack)-1] == '['
}

func nextJSONArrayValueNeedsComma(raw string, start int) bool {
	i := start
	for i < len(raw) && isJSONWhitespace(raw[i]) {
		i++
	}
	if i >= len(raw) {
		return false
	}
	switch raw[i] {
	case ',', ']':
		return false
	default:
		return isJSONValueStart(raw[i])
	}
}

func isJSONWhitespace(ch byte) bool {
	switch ch {
	case ' ', '\n', '\r', '\t':
		return true
	default:
		return false
	}
}

func isJSONValueStart(ch byte) bool {
	switch ch {
	case '"', '{', '[', 't', 'f', 'n':
		return true
	default:
		return isJSONNumberStart(ch)
	}
}

func isStandardJSONEscape(ch byte) bool {
	switch ch {
	case '"', '\\', '/', 'b', 'f', 'n', 'r', 't':
		return true
	default:
		return false
	}
}

func isHexQuartet(s string) bool {
	if len(s) != 4 {
		return false
	}
	for i := 0; i < len(s); i++ {
		ch := s[i]
		if (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F') {
			continue
		}
		return false
	}
	return true
}

type topLevelJSONFieldSpan struct {
	Key        string
	ValueStart int
	ValueEnd   int
}

func replaceTopLevelJSONObjectIDPlaceholder(compactJSON string, resolvedID string) (string, bool, error) {
	if compactJSON == "" || compactJSON[0] != '{' {
		return compactJSON, false, nil
	}

	fields, err := scanTopLevelJSONObjectFields(compactJSON)
	if err != nil {
		return compactJSON, false, err
	}

	for _, field := range fields {
		if field.Key != "id" {
			continue
		}

		var current string
		if err := json.Unmarshal([]byte(compactJSON[field.ValueStart:field.ValueEnd]), &current); err != nil {
			return compactJSON, false, fmt.Errorf("top-level id is not a string: %w", err)
		}
		if current != pendingGeneratedConverterUUID && current != pendingGeneratedConverterToken && current != "" {
			return compactJSON, false, nil
		}

		quoted, err := json.Marshal(resolvedID)
		if err != nil {
			return compactJSON, false, err
		}
		rewritten := compactJSON[:field.ValueStart] + string(quoted) + compactJSON[field.ValueEnd:]
		return rewritten, true, nil
	}

	return compactJSON, false, nil
}

func scanTopLevelJSONObjectFields(s string) ([]topLevelJSONFieldSpan, error) {
	if s == "" || s[0] != '{' {
		return nil, fmt.Errorf("expected compact JSON object")
	}

	i := 1
	if i < len(s) && s[i] == '}' {
		return nil, nil
	}

	var fields []topLevelJSONFieldSpan
	for {
		if i >= len(s) || s[i] != '"' {
			return nil, fmt.Errorf("expected object key at byte %d", i)
		}

		keyEnd, err := scanJSONStringEnd(s, i)
		if err != nil {
			return nil, err
		}
		var key string
		if err := json.Unmarshal([]byte(s[i:keyEnd]), &key); err != nil {
			return nil, fmt.Errorf("decode object key: %w", err)
		}
		i = keyEnd

		if i >= len(s) || s[i] != ':' {
			return nil, fmt.Errorf("expected ':' after key %q at byte %d", key, i)
		}
		i++

		valueStart := i
		valueEnd, err := scanJSONValueEnd(s, valueStart)
		if err != nil {
			return nil, err
		}
		fields = append(fields, topLevelJSONFieldSpan{
			Key:        key,
			ValueStart: valueStart,
			ValueEnd:   valueEnd,
		})
		i = valueEnd

		if i >= len(s) {
			return nil, fmt.Errorf("unexpected end of object after key %q", key)
		}
		if s[i] == '}' {
			return fields, nil
		}
		if s[i] != ',' {
			return nil, fmt.Errorf("expected ',' or '}' after key %q at byte %d", key, i)
		}
		i++
	}
}

func scanJSONValueEnd(s string, start int) (int, error) {
	if start >= len(s) {
		return 0, fmt.Errorf("expected JSON value at end of input")
	}

	switch s[start] {
	case '"':
		return scanJSONStringEnd(s, start)
	case '{':
		return scanJSONObjectEnd(s, start)
	case '[':
		return scanJSONArrayEnd(s, start)
	case 't':
		if strings.HasPrefix(s[start:], "true") {
			return start + 4, nil
		}
	case 'f':
		if strings.HasPrefix(s[start:], "false") {
			return start + 5, nil
		}
	case 'n':
		if strings.HasPrefix(s[start:], "null") {
			return start + 4, nil
		}
	default:
		if isJSONNumberStart(s[start]) {
			i := start + 1
			for i < len(s) && !isJSONValueDelimiter(s[i]) {
				i++
			}
			return i, nil
		}
	}

	return 0, fmt.Errorf("invalid JSON value at byte %d", start)
}

func scanJSONObjectEnd(s string, start int) (int, error) {
	if s[start] != '{' {
		return 0, fmt.Errorf("expected '{' at byte %d", start)
	}

	i := start + 1
	if i < len(s) && s[i] == '}' {
		return i + 1, nil
	}

	for {
		if i >= len(s) || s[i] != '"' {
			return 0, fmt.Errorf("expected nested object key at byte %d", i)
		}
		keyEnd, err := scanJSONStringEnd(s, i)
		if err != nil {
			return 0, err
		}
		i = keyEnd

		if i >= len(s) || s[i] != ':' {
			return 0, fmt.Errorf("expected ':' in nested object at byte %d", i)
		}
		i++

		valueEnd, err := scanJSONValueEnd(s, i)
		if err != nil {
			return 0, err
		}
		i = valueEnd

		if i >= len(s) {
			return 0, fmt.Errorf("unexpected end of nested object")
		}
		if s[i] == '}' {
			return i + 1, nil
		}
		if s[i] != ',' {
			return 0, fmt.Errorf("expected ',' or '}' in nested object at byte %d", i)
		}
		i++
	}
}

func scanJSONArrayEnd(s string, start int) (int, error) {
	if s[start] != '[' {
		return 0, fmt.Errorf("expected '[' at byte %d", start)
	}

	i := start + 1
	if i < len(s) && s[i] == ']' {
		return i + 1, nil
	}

	for {
		valueEnd, err := scanJSONValueEnd(s, i)
		if err != nil {
			return 0, err
		}
		i = valueEnd

		if i >= len(s) {
			return 0, fmt.Errorf("unexpected end of array")
		}
		if s[i] == ']' {
			return i + 1, nil
		}
		if s[i] != ',' {
			return 0, fmt.Errorf("expected ',' or ']' in array at byte %d", i)
		}
		i++
	}
}

func scanJSONStringEnd(s string, start int) (int, error) {
	if start >= len(s) || s[start] != '"' {
		return 0, fmt.Errorf("expected string at byte %d", start)
	}

	for i := start + 1; i < len(s); i++ {
		switch s[i] {
		case '"':
			return i + 1, nil
		case '\\':
			i++
			if i >= len(s) {
				return 0, fmt.Errorf("unterminated escape at byte %d", start)
			}
			if s[i] == 'u' {
				if i+4 >= len(s) {
					return 0, fmt.Errorf("short unicode escape at byte %d", start)
				}
				i += 4
			}
		}
	}
	return 0, fmt.Errorf("unterminated string at byte %d", start)
}

func isJSONNumberStart(ch byte) bool {
	return ch == '-' || (ch >= '0' && ch <= '9')
}

func isJSONValueDelimiter(ch byte) bool {
	switch ch {
	case ',', '}', ']':
		return true
	default:
		return false
	}
}
