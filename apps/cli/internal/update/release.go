package update

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
)

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
