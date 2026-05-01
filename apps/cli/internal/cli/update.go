package cli

import (
	"archive/tar"
	"archive/zip"
	"bufio"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

const (
	updateRepoOwner = "PUDAP"
	updateRepoName  = "puda"
	updateAPIBase   = "https://api.github.com/repos/" + updateRepoOwner + "/" + updateRepoName
	updateHTTPTO    = 60 * time.Second
)

var (
	updateTargetVersion string
	updateYes           bool
)

var updateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update the puda CLI to the latest (or a specific) release",
	Long: `Download and install a release of the puda CLI from GitHub.

Without --version, the latest release is installed. With --version, a specific
tag is installed; downgrading will print a warning and require confirmation.

The binary is replaced in place at the path reported by 'which puda'
(os.Executable). Use --yes/-y for non-interactive mode.`,
	Example: `  # Upgrade to the latest release
  puda update

  # Install a specific release (upgrade or downgrade)
  puda update --version v1.5.0

  # Non-interactive (useful in scripts)
  puda update --version v1.5.0 --yes`,
	RunE: func(cmd *cobra.Command, args []string) error {
		return runUpdate(cmd)
	},
}

func init() {
	updateCmd.Flags().StringVar(&updateTargetVersion, "version", "", "Release tag to install (e.g. v1.5.0). Defaults to the latest release.")
	updateCmd.Flags().BoolVarP(&updateYes, "yes", "y", false, "Skip confirmation prompts (non-interactive mode)")
	rootCmd.AddCommand(updateCmd)
}

// githubRelease models the subset of the GitHub release JSON we care about.
type githubRelease struct {
	TagName string `json:"tag_name"`
	Name    string `json:"name"`
	Body    string `json:"body"`
	HTMLURL string `json:"html_url"`
	Assets  []struct {
		Name               string `json:"name"`
		BrowserDownloadURL string `json:"browser_download_url"`
		Size               int64  `json:"size"`
	} `json:"assets"`
}

func runUpdate(cmd *cobra.Command) error {
	out := cmd.OutOrStdout()

	fmt.Fprintln(out, "Checking for updates...")

	release, err := fetchRelease(updateTargetVersion)
	if err != nil {
		return err
	}

	currentTag := normalizeTag(Version)
	targetTag := normalizeTag(release.TagName)

	fmt.Fprintf(out, "Current version: %s\n", displayVersion(Version))
	fmt.Fprintf(out, "Latest version:  %s\n\n", targetTag)

	cmp := compareSemver(currentTag, targetTag)

	// Same version: nothing to do.
	if cmp == 0 && Version != "dev" {
		fmt.Fprintf(out, "puda cli is already on %s. Nothing to do.\n", targetTag)
		return nil
	}

	printChangelog(out, currentTag, targetTag, release, cmp)

	// Confirm / warn.
	if cmp > 0 {
		fmt.Fprintf(out, "\u26A0\uFE0F  Warning: You are downgrading from %s to %s.\n", currentTag, targetTag)
		fmt.Fprintln(out, "Older versions may not be able to read configuration files created by newer versions.")
		fmt.Fprintln(out)
		if !updateYes {
			if !promptConfirm(cmd, "Are you sure you want to proceed?", false) {
				fmt.Fprintln(out, "Aborted.")
				return nil
			}
		}
	} else if !updateYes {
		if !promptConfirm(cmd, "? A new version is available. Would you like to install it?", true) {
			fmt.Fprintln(out, "Aborted.")
			return nil
		}
	}

	// Pick the asset for this OS / arch.
	archiveName, err := expectedArchiveName()
	if err != nil {
		return err
	}
	var archiveURL string
	var archiveSize int64
	var checksumURL string
	for _, a := range release.Assets {
		switch {
		case a.Name == archiveName:
			archiveURL = a.BrowserDownloadURL
			archiveSize = a.Size
		case strings.HasSuffix(a.Name, "_checksums.txt"):
			checksumURL = a.BrowserDownloadURL
		}
	}
	if archiveURL == "" {
		return fmt.Errorf("release %s has no asset matching %s (os=%s arch=%s)", targetTag, archiveName, runtime.GOOS, runtime.GOARCH)
	}
	if checksumURL == "" {
		return fmt.Errorf("release %s has no checksums file", targetTag)
	}

	// Download archive with progress.
	fmt.Fprintf(out, "> Downloading %s ", targetTag)
	archiveBytes, err := downloadWithProgress(out, archiveURL, archiveSize)
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}

	// Verify checksum.
	fmt.Fprint(out, "> Verifying checksum... ")
	if err := verifyChecksum(archiveBytes, archiveName, checksumURL); err != nil {
		fmt.Fprintln(out, "FAILED")
		return err
	}
	fmt.Fprintln(out, "Done.")

	// Extract binary and replace in place.
	fmt.Fprint(out, "> Applying update... ")
	if err := applyUpdate(archiveBytes, archiveName); err != nil {
		fmt.Fprintln(out, "FAILED")
		return err
	}
	fmt.Fprintln(out, "Done.")

	fmt.Fprintln(out)
	if cmp > 0 {
		fmt.Fprintf(out, "Success! puda cli has been downgraded to %s.\n", targetTag)
	} else {
		fmt.Fprintf(out, "Success! puda cli has been upgraded to %s.\n", targetTag)
	}
	if release.HTMLURL != "" {
		fmt.Fprintf(out, "Read the release notes here: %s\n", release.HTMLURL)
	}
	return nil
}

func printChangelog(w io.Writer, currentTag, targetTag string, targetRelease *githubRelease, cmp int) {
	releases, err := fetchChangelogBetween(currentTag, targetTag, targetRelease, cmp)
	fmt.Fprintf(w, "Changelog (%s -> %s):\n", displayVersion(currentTag), displayVersion(targetTag))
	if err != nil {
		fmt.Fprintf(w, "Could not fetch the complete changelog: %v\n", err)
		fmt.Fprintln(w, "Showing target release notes only.")
	}
	if len(releases) == 0 {
		fmt.Fprintln(w, "No release notes found.")
		fmt.Fprintln(w)
		return
	}

	for i, rel := range releases {
		tag := normalizeTag(rel.TagName)
		title := strings.TrimSpace(rel.Name)
		if title != "" && title != tag {
			fmt.Fprintf(w, "- %s - %s\n", tag, title)
		} else {
			fmt.Fprintf(w, "- %s\n", tag)
		}

		body := strings.TrimSpace(rel.Body)
		if body == "" {
			fmt.Fprintln(w, "  No release notes provided.")
		} else {
			printIndentedReleaseBody(w, body)
		}
		if rel.HTMLURL != "" {
			fmt.Fprintf(w, "  %s\n", rel.HTMLURL)
		}
		if i < len(releases)-1 {
			fmt.Fprintln(w)
		}
	}
	fmt.Fprintln(w)
}

func printIndentedReleaseBody(w io.Writer, body string) {
	for _, line := range strings.Split(body, "\n") {
		line = strings.TrimRight(line, "\r")
		if strings.TrimSpace(line) == "" {
			fmt.Fprintln(w)
			continue
		}
		fmt.Fprintf(w, "  %s\n", line)
	}
}

func fetchChangelogBetween(currentTag, targetTag string, targetRelease *githubRelease, cmp int) ([]githubRelease, error) {
	if cmp == 0 || !isParseableSemver(currentTag) || !isParseableSemver(targetTag) {
		return []githubRelease{*targetRelease}, nil
	}

	releases, err := fetchReleases()
	if err != nil {
		return []githubRelease{*targetRelease}, err
	}

	filtered := filterReleaseNotesBetween(releases, currentTag, targetTag, cmp)
	if len(filtered) == 0 {
		return []githubRelease{*targetRelease}, nil
	}
	if !containsReleaseTag(filtered, targetTag) {
		filtered = append(filtered, *targetRelease)
		sortReleaseNotes(filtered, cmp)
	}
	return filtered, nil
}

// fetchRelease talks to the GitHub API to resolve either the latest release
// (when tag is empty) or a specific release by tag.
func fetchRelease(tag string) (*githubRelease, error) {
	var url string
	if tag == "" {
		url = updateAPIBase + "/releases/latest"
	} else {
		url = updateAPIBase + "/releases/tags/" + normalizeTag(tag)
	}
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "puda-cli-updater")

	client := &http.Client{Timeout: updateHTTPTO}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to query GitHub: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		if tag == "" {
			return nil, fmt.Errorf("no releases found for %s/%s", updateRepoOwner, updateRepoName)
		}
		return nil, fmt.Errorf("release %s not found", tag)
	}
	if resp.StatusCode/100 != 2 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return nil, fmt.Errorf("GitHub API returned %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}

	var rel githubRelease
	if err := json.NewDecoder(resp.Body).Decode(&rel); err != nil {
		return nil, fmt.Errorf("failed to decode release metadata: %w", err)
	}
	return &rel, nil
}

func fetchReleases() ([]githubRelease, error) {
	client := &http.Client{Timeout: updateHTTPTO}
	var releases []githubRelease
	for page := 1; page <= 10; page++ {
		url := fmt.Sprintf("%s/releases?per_page=100&page=%d", updateAPIBase, page)
		req, err := http.NewRequest(http.MethodGet, url, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Accept", "application/vnd.github+json")
		req.Header.Set("User-Agent", "puda-cli-updater")

		resp, err := client.Do(req)
		if err != nil {
			return nil, fmt.Errorf("failed to query GitHub releases: %w", err)
		}
		body, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			return nil, readErr
		}
		if resp.StatusCode/100 != 2 {
			return nil, fmt.Errorf("GitHub API returned %s: %s", resp.Status, strings.TrimSpace(string(body)))
		}

		var pageReleases []githubRelease
		if err := json.Unmarshal(body, &pageReleases); err != nil {
			return nil, fmt.Errorf("failed to decode release list: %w", err)
		}
		if len(pageReleases) == 0 {
			break
		}
		releases = append(releases, pageReleases...)
		if len(pageReleases) < 100 {
			break
		}
	}
	return releases, nil
}

func filterReleaseNotesBetween(releases []githubRelease, currentTag, targetTag string, cmp int) []githubRelease {
	var out []githubRelease
	for _, rel := range releases {
		tag := normalizeTag(rel.TagName)
		if !isParseableSemver(tag) {
			continue
		}

		relToCurrent := compareSemver(tag, currentTag)
		relToTarget := compareSemver(tag, targetTag)
		if cmp < 0 && relToCurrent > 0 && relToTarget <= 0 {
			out = append(out, rel)
		}
		if cmp > 0 && relToTarget >= 0 && relToCurrent < 0 {
			out = append(out, rel)
		}
	}

	sortReleaseNotes(out, cmp)
	return out
}

func containsReleaseTag(releases []githubRelease, tag string) bool {
	tag = normalizeTag(tag)
	for _, rel := range releases {
		if normalizeTag(rel.TagName) == tag {
			return true
		}
	}
	return false
}

func sortReleaseNotes(releases []githubRelease, cmp int) {
	sort.SliceStable(releases, func(i, j int) bool {
		if cmp < 0 {
			return compareSemver(releases[i].TagName, releases[j].TagName) < 0
		}
		return compareSemver(releases[i].TagName, releases[j].TagName) > 0
	})
}

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

// promptConfirm asks a yes/no question on stdin.
func promptConfirm(cmd *cobra.Command, question string, defaultYes bool) bool {
	out := cmd.OutOrStdout()
	suffix := "(y/N):"
	if defaultYes {
		suffix = "(Y/n)"
	}
	fmt.Fprintf(out, "%s %s ", question, suffix)

	reader := bufio.NewReader(os.Stdin)
	line, err := reader.ReadString('\n')
	if err != nil && line == "" {
		return false
	}
	ans := strings.ToLower(strings.TrimSpace(line))
	if ans == "" {
		return defaultYes
	}
	return ans == "y" || ans == "yes"
}

// normalizeTag returns a tag guaranteed to have a leading "v" when it looks
// like a semver version (e.g. "1.2.3" -> "v1.2.3"). Non-semver strings
// (e.g. "dev") are returned unchanged.
func normalizeTag(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return s
	}
	if strings.HasPrefix(s, "v") || strings.HasPrefix(s, "V") {
		return "v" + strings.TrimPrefix(strings.TrimPrefix(s, "v"), "V")
	}
	if len(s) > 0 && s[0] >= '0' && s[0] <= '9' {
		return "v" + s
	}
	return s
}

func displayVersion(v string) string {
	if v == "dev" || v == "" {
		return "dev"
	}
	return normalizeTag(v)
}

// compareSemver returns -1 if a<b, 0 if equal, 1 if a>b.
// Accepts "vX.Y.Z" with optional pre-release (ignored for ordering).
// Returns 0 if either side is not a parseable version.
func compareSemver(a, b string) int {
	av, aok := parseSemver(a)
	bv, bok := parseSemver(b)
	if !aok || !bok {
		return 0
	}
	for i := 0; i < 3; i++ {
		if av[i] < bv[i] {
			return -1
		}
		if av[i] > bv[i] {
			return 1
		}
	}
	return 0
}

func parseSemver(s string) ([3]int, bool) {
	var out [3]int
	s = strings.TrimPrefix(normalizeTag(s), "v")
	if s == "" {
		return out, false
	}
	if i := strings.IndexAny(s, "-+"); i >= 0 {
		s = s[:i]
	}
	parts := strings.Split(s, ".")
	if len(parts) < 1 || len(parts) > 3 {
		return out, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

func isParseableSemver(s string) bool {
	_, ok := parseSemver(s)
	return ok
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}
