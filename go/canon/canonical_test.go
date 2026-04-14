package canon

// ---------------------------------------------------------------------------
// S30 — Unit tests for canonical JSON serializer and UUIDv5 computation.
//
// These tests verify the low-level building blocks independently of the
// batch_snapshot integration.
//
// Ref: S30 — canonical.go unit tests.
// ---------------------------------------------------------------------------

import (
	"encoding/json"
	"testing"
)

// TestCanonicalJSONSortsKeys verifies that CanonicalJSON sorts object keys
// lexicographically, regardless of input order.
func TestCanonicalJSONSortsKeys(t *testing.T) {
	// Use a map (Go sorts map keys in json.Marshal, but we want to verify
	// the full round-trip through CanonicalJSON).
	input := map[string]interface{}{
		"zebra":    1,
		"alpha":    2,
		"middle":   3,
	}

	canonical, err := CanonicalJSON(input)
	if err != nil {
		t.Fatalf("CanonicalJSON error: %v", err)
	}

	expected := `{"alpha":2,"middle":3,"zebra":1}`
	if string(canonical) != expected {
		t.Errorf("CanonicalJSON:\n  got:  %s\n  want: %s", canonical, expected)
	}
}

// TestCanonicalJSONStructFieldOrder verifies that structs are serialized
// with sorted keys, not struct declaration order.
func TestCanonicalJSONStructFieldOrder(t *testing.T) {
	type sample struct {
		Zebra  int    `json:"zebra"`
		Alpha  string `json:"alpha"`
		Middle bool   `json:"middle"`
	}

	input := sample{Zebra: 1, Alpha: "a", Middle: true}
	canonical, err := CanonicalJSON(input)
	if err != nil {
		t.Fatalf("CanonicalJSON error: %v", err)
	}

	// Keys must be sorted: alpha < middle < zebra.
	expected := `{"alpha":"a","middle":true,"zebra":1}`
	if string(canonical) != expected {
		t.Errorf("CanonicalJSON:\n  got:  %s\n  want: %s", canonical, expected)
	}
}

// TestCanonicalJSONNestedSorting verifies that nested objects also have
// their keys sorted.
func TestCanonicalJSONNestedSorting(t *testing.T) {
	input := map[string]interface{}{
		"outer_b": map[string]interface{}{
			"inner_z": 1,
			"inner_a": 2,
		},
		"outer_a": "value",
	}

	canonical, err := CanonicalJSON(input)
	if err != nil {
		t.Fatalf("CanonicalJSON error: %v", err)
	}

	expected := `{"outer_a":"value","outer_b":{"inner_a":2,"inner_z":1}}`
	if string(canonical) != expected {
		t.Errorf("CanonicalJSON:\n  got:  %s\n  want: %s", canonical, expected)
	}
}

// TestCanonicalJSONPreservesNumbers verifies that integer values are
// preserved through the canonical round-trip (no float64 coercion).
func TestCanonicalJSONPreservesNumbers(t *testing.T) {
	input := map[string]interface{}{
		"count": 42,
		"big":   1234567890123,
	}

	canonical, err := CanonicalJSON(input)
	if err != nil {
		t.Fatalf("CanonicalJSON error: %v", err)
	}

	// Verify the numbers don't have decimal points.
	var parsed map[string]json.Number
	if err := json.Unmarshal(canonical, &parsed); err != nil {
		t.Fatalf("parse canonical: %v", err)
	}
	if parsed["count"].String() != "42" {
		t.Errorf("count: got %s, want 42", parsed["count"])
	}
	if parsed["big"].String() != "1234567890123" {
		t.Errorf("big: got %s, want 1234567890123", parsed["big"])
	}
}

// TestCanonicalJSONDeterministic verifies that multiple calls produce
// identical output.
func TestCanonicalJSONDeterministic(t *testing.T) {
	input := map[string]interface{}{
		"b": []interface{}{"x", "y"},
		"a": 1,
	}

	c1, err := CanonicalJSON(input)
	if err != nil {
		t.Fatalf("first call: %v", err)
	}
	c2, err := CanonicalJSON(input)
	if err != nil {
		t.Fatalf("second call: %v", err)
	}

	if string(c1) != string(c2) {
		t.Errorf("not deterministic:\n  c1: %s\n  c2: %s", c1, c2)
	}
}

// TestUUIDv5KnownVector verifies the UUIDv5 implementation against
// the well-known test vector from RFC 4122:
//   UUIDv5(NamespaceDNS, "python.org") = 886313e1-3b8a-5372-9b90-0c9aee199e5d
//
// NamespaceDNS = 6ba7b810-9dad-11d1-80b4-00c04fd430c8
func TestUUIDv5KnownVector(t *testing.T) {
	namespaceDNS := [16]byte{
		0x6b, 0xa7, 0xb8, 0x10,
		0x9d, 0xad,
		0x11, 0xd1,
		0x80, 0xb4,
		0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8,
	}

	uuid := UUIDv5(namespaceDNS, []byte("python.org"))
	expected := "886313e1-3b8a-5372-9b90-0c9aee199e5d"
	if uuid != expected {
		t.Errorf("UUIDv5 known vector:\n  got:  %s\n  want: %s", uuid, expected)
	}
}

// TestUUIDv5Deterministic verifies that the same inputs always produce
// the same UUID.
func TestUUIDv5Deterministic(t *testing.T) {
	name := []byte("test-determinism")
	u1 := UUIDv5(UUIDNamespaceURL, name)
	u2 := UUIDv5(UUIDNamespaceURL, name)

	if u1 != u2 {
		t.Errorf("not deterministic: %s vs %s", u1, u2)
	}
}

// TestUUIDv5DifferentInputs verifies that different inputs produce
// different UUIDs.
func TestUUIDv5DifferentInputs(t *testing.T) {
	u1 := UUIDv5(UUIDNamespaceURL, []byte("input-a"))
	u2 := UUIDv5(UUIDNamespaceURL, []byte("input-b"))

	if u1 == u2 {
		t.Errorf("different inputs produced same UUID: %s", u1)
	}
}

// TestUUIDv5VersionAndVariant verifies that the UUID has the correct
// version (5) and variant (RFC 4122) bits.
func TestUUIDv5VersionAndVariant(t *testing.T) {
	uuid := UUIDv5(UUIDNamespaceURL, []byte("test-version-variant"))

	// Format: xxxxxxxx-xxxx-Vxxx-Yxxx-xxxxxxxxxxxx
	// V = version nibble (position 14 in string)
	// Y = variant nibble (position 19 in string), high 2 bits = 10
	if len(uuid) != 36 {
		t.Fatalf("UUID wrong length: %d (%s)", len(uuid), uuid)
	}
	if uuid[14] != '5' {
		t.Errorf("version nibble: got %c, want 5", uuid[14])
	}
	// Variant: hex digit at position 19 must be 8, 9, a, or b.
	variantChar := uuid[19]
	if variantChar != '8' && variantChar != '9' && variantChar != 'a' && variantChar != 'b' {
		t.Errorf("variant nibble: got %c, want 8/9/a/b", variantChar)
	}
}

// TestComputeSnapshotUUIDDeterministic verifies the full UUID computation
// pipeline is deterministic.
func TestComputeSnapshotUUIDDeterministic(t *testing.T) {
	runs := []string{"run-001", "run-002", "run-003"}

	u1, err := ComputeSnapshotUUID("v0.1", "fold_v1", runs)
	if err != nil {
		t.Fatalf("first call: %v", err)
	}
	u2, err := ComputeSnapshotUUID("v0.1", "fold_v1", runs)
	if err != nil {
		t.Fatalf("second call: %v", err)
	}

	if u1 != u2 {
		t.Errorf("not deterministic: %s vs %s", u1, u2)
	}
}

// TestComputeSnapshotUUIDChangesWithRuns verifies that different
// runs_included sets produce different UUIDs.
func TestComputeSnapshotUUIDChangesWithRuns(t *testing.T) {
	u1, _ := ComputeSnapshotUUID("v0.1", "fold_v1", []string{"run-001"})
	u2, _ := ComputeSnapshotUUID("v0.1", "fold_v1", []string{"run-001", "run-002"})

	if u1 == u2 {
		t.Errorf("different runs produced same UUID: %s", u1)
	}
}

// TestSnapshotUUIDPayloadKeys verifies the payload has the expected keys.
func TestSnapshotUUIDPayloadKeys(t *testing.T) {
	payload := SnapshotUUIDPayload("v0.1", "fold_v1", []string{"run-001"})

	expectedKeys := []string{
		"accumulation_version",
		"algorithm_id",
		"runs_included",
		"type",
		"uuid_spec_version",
	}

	if len(payload) != len(expectedKeys) {
		t.Fatalf("payload has %d keys, want %d", len(payload), len(expectedKeys))
	}

	for _, k := range expectedKeys {
		if _, ok := payload[k]; !ok {
			t.Errorf("missing key: %s", k)
		}
	}

	if payload["type"] != "batch_snapshot" {
		t.Errorf("type: got %v, want batch_snapshot", payload["type"])
	}
	if payload["uuid_spec_version"] != UUIDSpecVersionV1 {
		t.Errorf("uuid_spec_version: got %v, want %s", payload["uuid_spec_version"], UUIDSpecVersionV1)
	}
}
