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

// tw5TimestampLayout is the TiddlyWiki 5 timestamp format: YYYYMMDDHHmmss.
const tw5TimestampLayout = "20060102150405"

// parseTW5Timestamp attempts to parse a TW5 timestamp string for created/modified fields.
// TW5 timestamps are 17-digit strings: YYYYMMDDHHmmssSSS.
// The last 3 digits are milliseconds (SSS).
//
// Policy (S09): Preserve milliseconds when present to maintain temporal
// precision from the source. This applies to both created and modified timestamps.
// The Ingesta is pre-canonical and should not lose valid information silently.
// Malformed milliseconds (non-numeric, out of range) are silently ignored and
// do not produce errors — the timestamp is preserved at second precision.
//
// This is the first closed semantic policy of Ingesta validated against real corpus (S08).
//
// Returns nil, nil for empty input; nil, error for malformed base timestamp.
func parseTW5Timestamp(raw string) (*time.Time, error) {
	if raw == "" {
		return nil, nil
	}

	cleaned := strings.TrimSpace(raw)
	if len(cleaned) < 14 {
		return nil, fmt.Errorf("timestamp too short: %q", raw)
	}

	// Parse the base timestamp (first 14 digits: YYYYMMDDHHmmss)
	t, err := time.Parse(tw5TimestampLayout, cleaned[:14])
	if err != nil {
		return nil, fmt.Errorf("cannot parse timestamp %q: %w", raw, err)
	}

	// If there are milliseconds (positions 14-16), add them
	if len(cleaned) >= 17 {
		msStr := cleaned[14:17]
		// Parse milliseconds (000-999)
		var ms int
		if _, err := fmt.Sscanf(msStr, "%03d", &ms); err == nil && ms >= 0 && ms <= 999 {
			// Add milliseconds as nanoseconds to the parsed time
			t = t.Add(time.Duration(ms) * time.Millisecond)
		}
		// If milliseconds are malformed, we silently ignore them and
		// preserve the second-precision timestamp (no error).
	}

	return &t, nil
}
