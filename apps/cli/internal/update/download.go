package update

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"runtime"
	"strings"
	"time"
)

// expectedArchiveName returns the release asset name for the current platform,
// matching the naming used by goreleaser for this project.
func expectedArchiveName() (string, error) {
	var archPart string
	switch runtime.GOARCH {
	case "amd64":
		archPart = "x86_64"
	case "arm64":
		archPart = "arm64"
	case "386":
		archPart = "i386"
	default:
		return "", fmt.Errorf("unsupported architecture: %s", runtime.GOARCH)
	}

	switch runtime.GOOS {
	case "linux":
		return fmt.Sprintf("puda_linux_%s.tar.gz", archPart), nil
	case "darwin":
		return fmt.Sprintf("puda_darwin_%s.tar.gz", archPart), nil
	case "windows":
		return fmt.Sprintf("puda_windows_%s.zip", archPart), nil
	default:
		return "", fmt.Errorf("unsupported operating system: %s", runtime.GOOS)
	}
}

// downloadWithProgress downloads url into memory while rendering a simple
// progress bar to w.
func downloadWithProgress(w io.Writer, url string, expected int64) ([]byte, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "puda-cli-updater")

	client := &http.Client{Timeout: 10 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return nil, fmt.Errorf("unexpected status %s downloading %s", resp.Status, url)
	}

	total := expected
	if total <= 0 {
		total = resp.ContentLength
	}

	buf := make([]byte, 0, max64(total, 1<<20))
	chunk := make([]byte, 32*1024)
	var read int64
	lastDraw := time.Now().Add(-time.Second)
	drawBar(w, read, total, false)
	for {
		n, rerr := resp.Body.Read(chunk)
		if n > 0 {
			buf = append(buf, chunk[:n]...)
			read += int64(n)
			if time.Since(lastDraw) > 80*time.Millisecond {
				drawBar(w, read, total, false)
				lastDraw = time.Now()
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			fmt.Fprintln(w)
			return nil, rerr
		}
	}
	drawBar(w, read, total, true)
	return buf, nil
}

// drawBar renders "[####....] 100%" in place on the current line.
func drawBar(w io.Writer, read, total int64, final bool) {
	const width = 20
	var pct float64
	if total > 0 {
		pct = float64(read) / float64(total)
		if pct > 1 {
			pct = 1
		}
	}
	filled := int(pct * float64(width))
	if filled > width {
		filled = width
	}
	bar := strings.Repeat("\u2588", filled) + strings.Repeat(" ", width-filled)
	if total > 0 {
		fmt.Fprintf(w, "\r> Downloading [%s] %3d%%", bar, int(pct*100))
	} else {
		fmt.Fprintf(w, "\r> Downloading [%s] %s", bar, humanBytes(read))
	}
	if final {
		fmt.Fprintln(w)
	}
}

func humanBytes(n int64) string {
	const k = 1024
	if n < k {
		return fmt.Sprintf("%d B", n)
	}
	units := []string{"KB", "MB", "GB", "TB"}
	v := float64(n) / k
	i := 0
	for v >= k && i < len(units)-1 {
		v /= k
		i++
	}
	return fmt.Sprintf("%.1f %s", v, units[i])
}

// verifyChecksum fetches the checksums.txt file, locates the entry for
// archiveName and compares it to the sha256 of data.
func verifyChecksum(data []byte, archiveName, checksumURL string) error {
	req, err := http.NewRequest(http.MethodGet, checksumURL, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "puda-cli-updater")
	client := &http.Client{Timeout: updateHTTPTO}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to fetch checksums: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("unexpected status %s fetching checksums", resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	var expected string
	for _, line := range strings.Split(string(body), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) != 2 {
			continue
		}
		if fields[1] == archiveName {
			expected = strings.ToLower(fields[0])
			break
		}
	}
	if expected == "" {
		return fmt.Errorf("no checksum entry for %s", archiveName)
	}

	sum := sha256.Sum256(data)
	got := hex.EncodeToString(sum[:])
	if got != expected {
		return fmt.Errorf("checksum mismatch for %s: expected %s, got %s", archiveName, expected, got)
	}
	return nil
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}
