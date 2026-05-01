package update

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// applyUpdate extracts the puda binary from the archive and replaces the
// currently running binary with it.
func applyUpdate(archive []byte, archiveName string) error {
	binaryName := "puda"
	if runtime.GOOS == "windows" {
		binaryName = "puda.exe"
	}

	var binary []byte
	var err error
	if strings.HasSuffix(archiveName, ".zip") {
		binary, err = extractZipEntry(archive, binaryName)
	} else {
		binary, err = extractTarGzEntry(archive, binaryName)
	}
	if err != nil {
		return err
	}
	if len(binary) == 0 {
		return fmt.Errorf("archive did not contain %s", binaryName)
	}

	exe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to resolve current executable: %w", err)
	}
	// Resolve symlinks so we overwrite the real file, not the link.
	if resolved, err := filepath.EvalSymlinks(exe); err == nil {
		exe = resolved
	}

	dir := filepath.Dir(exe)
	tmp, err := os.CreateTemp(dir, ".puda-update-*")
	if err != nil {
		return fmt.Errorf("failed to create temp file next to %s: %w", exe, err)
	}
	tmpPath := tmp.Name()
	cleanup := func() { _ = os.Remove(tmpPath) }

	if _, err := tmp.Write(binary); err != nil {
		tmp.Close()
		cleanup()
		return fmt.Errorf("failed to write new binary: %w", err)
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return err
	}
	if err := os.Chmod(tmpPath, 0o755); err != nil {
		cleanup()
		return err
	}

	if runtime.GOOS == "windows" {
		old := exe + ".old"
		_ = os.Remove(old)
		if err := os.Rename(exe, old); err != nil {
			cleanup()
			return fmt.Errorf("failed to move existing binary aside: %w", err)
		}
		if err := os.Rename(tmpPath, exe); err != nil {
			_ = os.Rename(old, exe)
			cleanup()
			return fmt.Errorf("failed to install new binary: %w", err)
		}
		return nil
	}

	if err := os.Rename(tmpPath, exe); err != nil {
		cleanup()
		return fmt.Errorf("failed to install new binary at %s: %w", exe, err)
	}
	return nil
}

func extractTarGzEntry(data []byte, entryName string) ([]byte, error) {
	gzr, err := gzip.NewReader(strings.NewReader(string(data)))
	if err != nil {
		return nil, fmt.Errorf("invalid gzip: %w", err)
	}
	defer gzr.Close()
	tr := tar.NewReader(gzr)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			return nil, fmt.Errorf("entry %s not found in archive", entryName)
		}
		if err != nil {
			return nil, err
		}
		if filepath.Base(hdr.Name) != entryName || hdr.Typeflag != tar.TypeReg {
			continue
		}
		return io.ReadAll(tr)
	}
}

func extractZipEntry(data []byte, entryName string) ([]byte, error) {
	zr, err := zip.NewReader(&bytesReaderAt{data: data}, int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("invalid zip: %w", err)
	}
	for _, f := range zr.File {
		if filepath.Base(f.Name) != entryName || f.FileInfo().IsDir() {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return nil, err
		}
		defer rc.Close()
		return io.ReadAll(rc)
	}
	return nil, fmt.Errorf("entry %s not found in archive", entryName)
}

// bytesReaderAt lets us feed an in-memory byte slice to zip.NewReader.
type bytesReaderAt struct{ data []byte }

func (b *bytesReaderAt) ReadAt(p []byte, off int64) (int, error) {
	if off < 0 || off >= int64(len(b.data)) {
		return 0, io.EOF
	}
	n := copy(p, b.data[off:])
	if n < len(p) {
		return n, io.EOF
	}
	return n, nil
}
