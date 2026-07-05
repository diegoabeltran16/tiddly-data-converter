package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFileSHA256Label(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "source.html")
	if err := os.WriteFile(path, []byte("abc"), 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	got, err := fileSHA256Label(path)
	if err != nil {
		t.Fatalf("fileSHA256Label: %v", err)
	}

	want := "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	if got != want {
		t.Fatalf("hash = %q, want %q", got, want)
	}
}
