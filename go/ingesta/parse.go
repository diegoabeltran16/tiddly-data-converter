package ingesta

import (
	"fmt"
	"strings"
	"time"
)

// ParseTW5Tags parses a TiddlyWiki 5 tag string into individual tags.
//
// TW5 format: [[multi word tag]] singleTag [[another tag]]
//
// Ref: S05 §9.2 — Tiddler con campo tags como string.
func ParseTW5Tags(raw string) ([]string, error) {
	var tags []string
	s := strings.TrimSpace(raw)
	i := 0
	for i < len(s) {
		if s[i] == ' ' {
			i++
			continue
		}
		if strings.HasPrefix(s[i:], "[[") {
			end := strings.Index(s[i:], "]]")
			if end == -1 {
				return tags, fmt.Errorf("unclosed [[ in tag string at position %d", i)
			}
			tag := s[i+2 : i+end]
			if tag != "" {
				tags = append(tags, tag)
			}
			i += end + 2
		} else {
			end := strings.IndexByte(s[i:], ' ')
			if end == -1 {
				tags = append(tags, s[i:])
				break
			}
			tags = append(tags, s[i:i+end])
			i += end
		}
	}
	return tags, nil
}

// tw5TimestampLayout is the TiddlyWiki 5 timestamp format: YYYYMMDDHHmmssSSS.
const tw5TimestampLayout = "20060102150405"

// parseTW5Timestamp attempts to parse a TW5 timestamp string.
// TW5 timestamps are 17-digit strings: YYYYMMDDHHmmssSSS.
// Returns nil, nil for empty input; nil, error for malformed input.
func parseTW5Timestamp(raw string) (*time.Time, error) {
	if raw == "" {
		return nil, nil
	}

	// TW5 timestamps are typically 17 chars (14 digits + 3 ms).
	// We parse the first 14 as the core timestamp.
	cleaned := strings.TrimSpace(raw)
	if len(cleaned) < 14 {
		return nil, fmt.Errorf("timestamp too short: %q", raw)
	}

	t, err := time.Parse(tw5TimestampLayout, cleaned[:14])
	if err != nil {
		return nil, fmt.Errorf("cannot parse timestamp %q: %w", raw, err)
	}
	return &t, nil
}
