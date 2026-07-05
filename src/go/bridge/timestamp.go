package bridge

import (
	"fmt"
	"time"
)

// FormatTW5Timestamp converts a time.Time back to TW5 17-digit timestamp
// format: YYYYMMDDHHmmssSSS.
//
// This is the inverse of ingesta.parseTW5Timestamp. Milliseconds are
// extracted from the nanosecond component of the time.Time value, which
// is where Ingesta stores them per the S09 timestamp preservation policy.
//
// The result is always exactly 17 characters, zero-padded.
//
// Ref: S09 — timestamp preservation policy.
// Ref: S17 — bridge carries timestamps into CanonEntry shape.
func FormatTW5Timestamp(t time.Time) string {
	ms := t.Nanosecond() / int(time.Millisecond)
	return fmt.Sprintf("%s%03d", t.Format("20060102150405"), ms)
}
