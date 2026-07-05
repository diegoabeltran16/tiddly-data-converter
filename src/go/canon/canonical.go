package canon

// ---------------------------------------------------------------------------
// S30 — canon-uuidv5-and-memory-policy-v0
//
// Canonical JSON serializer and UUIDv5 computation for deterministic
// identity of batch_snapshot values.
//
// Canonical JSON: marshals any Go value to JSON with keys sorted
// lexicographically (recursively), preserving number precision via
// json.Number. This is a subset of RFC 8785 (JCS) sufficient for
// the repository's determinism requirements.
//
// UUIDv5: implemented using Go stdlib (crypto/sha1) per RFC 4122 §4.3.
// No external dependency required.
//
// Ref: S30 — UUIDv5 and canonical JSON for batch_snapshot identity.
// Ref: S29 — truth pin for checksum rule.
// ---------------------------------------------------------------------------

import (
	"bytes"
	"crypto/sha1"
	"encoding/json"
	"fmt"
)

// CanonicalJSON serializes v to JSON with all object keys sorted
// lexicographically at every nesting level. Numbers are preserved
// via json.Number to avoid float64 precision loss.
//
// The result is deterministic: the same Go value always produces
// the same byte sequence regardless of struct field declaration order.
//
// Ref: S30 — canonical JSON for checksum and UUIDv5 payload.
func CanonicalJSON(v interface{}) ([]byte, error) {
	// Step 1: marshal to JSON using Go's default encoder.
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, fmt.Errorf("canonical: marshal: %w", err)
	}

	// Step 2: unmarshal into a generic interface{} tree.
	// UseNumber preserves integer precision (no float64 coercion).
	var generic interface{}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&generic); err != nil {
		return nil, fmt.Errorf("canonical: decode: %w", err)
	}

	// Step 3: re-marshal. Go's json.Marshal sorts map[string]interface{}
	// keys lexicographically, which gives us canonical key ordering.
	canonical, err := json.Marshal(generic)
	if err != nil {
		return nil, fmt.Errorf("canonical: re-marshal: %w", err)
	}
	return canonical, nil
}

// ---------------------------------------------------------------------------
// UUIDv5 — RFC 4122 §4.3 (Name-Based UUID using SHA-1)
// ---------------------------------------------------------------------------

// UUIDNamespaceURL is the well-known namespace UUID for URLs (RFC 4122 Appendix C).
// Used as the namespace for batch_snapshot identity computation.
//
// Value: 6ba7b811-9dad-11d1-80b4-00c04fd430c8
var UUIDNamespaceURL = [16]byte{
	0x6b, 0xa7, 0xb8, 0x11,
	0x9d, 0xad,
	0x11, 0xd1,
	0x80, 0xb4,
	0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8,
}

// UUIDv5 computes a version-5 UUID from a namespace and a name,
// per RFC 4122 §4.3.
//
// The algorithm:
//   1. Concatenate namespace (16 bytes) + name (arbitrary bytes).
//   2. Compute SHA-1 hash.
//   3. Take the first 16 bytes of the hash.
//   4. Set version bits (byte 6, high nibble = 0101 → version 5).
//   5. Set variant bits (byte 8, high 2 bits = 10 → RFC 4122 variant).
//   6. Format as canonical UUID string.
//
// Ref: S30 — UUIDv5 for batch_snapshot identity.
func UUIDv5(namespace [16]byte, name []byte) string {
	h := sha1.New()
	h.Write(namespace[:])
	h.Write(name)
	sum := h.Sum(nil) // 20 bytes

	// Take first 16 bytes.
	var uuid [16]byte
	copy(uuid[:], sum[:16])

	// Set version 5 (byte 6, high nibble).
	uuid[6] = (uuid[6] & 0x0f) | 0x50

	// Set variant RFC 4122 (byte 8, high 2 bits = 10).
	uuid[8] = (uuid[8] & 0x3f) | 0x80

	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		uuid[0:4], uuid[4:6], uuid[6:8], uuid[8:10], uuid[10:16])
}

// UUIDSpecVersionV1 is the declared spec version for the UUIDv5 identity
// computation of batch_snapshot.
//
// This version identifier is embedded in the UUID payload so that
// future changes to the payload schema produce different UUIDs by design.
//
// Ref: S30 — uuid_spec_version decision.
const UUIDSpecVersionV1 = "v1"

// SnapshotUUIDPayload builds the canonical payload object whose
// Canonical JSON UTF-8 serialization serves as the UUIDv5 "name" input.
//
// Payload keys (sorted in canonical JSON):
//   accumulation_version, algorithm_id, runs_included, type, uuid_spec_version
//
// The payload is deterministic: same runs_included (already sorted by
// FoldV1) → same canonical JSON → same UUIDv5.
//
// Ref: S30 Decision 1 — UUIDv5 payload specification.
func SnapshotUUIDPayload(accumulationVersion, algorithmID string, runsIncluded []string) map[string]interface{} {
	// Convert []string to []interface{} for consistent JSON marshaling.
	runs := make([]interface{}, len(runsIncluded))
	for i, r := range runsIncluded {
		runs[i] = r
	}
	return map[string]interface{}{
		"type":                 "batch_snapshot",
		"uuid_spec_version":   UUIDSpecVersionV1,
		"accumulation_version": accumulationVersion,
		"algorithm_id":         algorithmID,
		"runs_included":        runs,
	}
}

// ComputeSnapshotUUID computes the deterministic UUIDv5 for a
// batch_snapshot given its accumulation metadata and sorted runs.
//
// The UUID is computed as:
//   UUIDv5(UUIDNamespaceURL, CanonicalJSON(payload))
//
// where payload is the object built by SnapshotUUIDPayload.
//
// Ref: S30 Decision 1 — UUIDv5 computation.
func ComputeSnapshotUUID(accumulationVersion, algorithmID string, runsIncluded []string) (string, error) {
	payload := SnapshotUUIDPayload(accumulationVersion, algorithmID, runsIncluded)
	name, err := CanonicalJSON(payload)
	if err != nil {
		return "", fmt.Errorf("snapshot uuid: canonical payload: %w", err)
	}
	return UUIDv5(UUIDNamespaceURL, name), nil
}
