package update

import (
	"fmt"
	"runtime"
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

// Run updates the currently running puda CLI binary.
func Run(cmd *cobra.Command, targetVersion string, yes bool, currentVersion string) error {
	out := cmd.OutOrStdout()

	fmt.Fprintln(out, "Checking for updates...")

	release, err := fetchRelease(targetVersion)
	if err != nil {
		return err
	}

	currentTag := normalizeTag(currentVersion)
	targetTag := normalizeTag(release.TagName)

	fmt.Fprintf(out, "Current version: %s\n", displayVersion(currentVersion))
	fmt.Fprintf(out, "Latest version:  %s\n\n", targetTag)

	cmp := compareSemver(currentTag, targetTag)

	// Same version: nothing to do.
	if cmp == 0 && currentVersion != "dev" {
		fmt.Fprintf(out, "puda cli is already on %s. Nothing to do.\n", targetTag)
		return nil
	}

	printChangelog(out, currentTag, targetTag, release, cmp)

	// Confirm / warn.
	if cmp > 0 {
		fmt.Fprintf(out, "\u26A0\uFE0F  Warning: You are downgrading from %s to %s.\n", currentTag, targetTag)
		fmt.Fprintln(out, "Older versions may not be able to read configuration files created by newer versions.")
		fmt.Fprintln(out)
		if !yes {
			if !promptConfirm(cmd, "Are you sure you want to proceed?", false) {
				fmt.Fprintln(out, "Aborted.")
				return nil
			}
		}
	} else if !yes {
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
