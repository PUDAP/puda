package update

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"time"

	compatibility "github.com/PUDAP/puda"
)

const compatibilityTimeout = 10 * time.Second
const compatibilityMaxBytes = 1 << 20

var commitSHA = regexp.MustCompile(`^[0-9a-f]{40}$`)
var compatibilityTag = regexp.MustCompile(`^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?(\+[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?$`)

// FetchCompatibility resolves the selected release's exact tag in the updater's
// fixed repository, peels annotated tags, then reads root metadata at that commit.
// No branch/latest/bundled fallback is allowed. Trust is GitHub HTTPS and repository
// ownership, just like release lookup, not a signature binding source to a binary.
func FetchCompatibility(ctx context.Context, tag string) (compatibility.Policy, error) {
	ctx, cancel := context.WithTimeout(ctx, compatibilityTimeout)
	defer cancel()
	client := &http.Client{Timeout: compatibilityTimeout, CheckRedirect: func(*http.Request, []*http.Request) error {
		return fmt.Errorf("compatibility metadata redirect refused")
	}}
	return fetchCompatibility(ctx, client, updateAPIBase, tag)
}

func fetchCompatibility(ctx context.Context, client *http.Client, base, tag string) (compatibility.Policy, error) {
	var empty compatibility.Policy
	if !compatibilityTag.MatchString(tag) {
		return empty, fmt.Errorf("invalid target release tag %q", tag)
	}
	var ref struct {
		Object struct {
			Type string `json:"type"`
			SHA  string `json:"sha"`
		} `json:"object"`
	}
	if err := compatibilityJSON(ctx, client, base+"/git/ref/tags/"+url.PathEscape(tag), &ref); err != nil {
		return empty, err
	}
	for depth := 0; ; depth++ {
		if !commitSHA.MatchString(ref.Object.SHA) {
			return empty, fmt.Errorf("invalid target object SHA")
		}
		if ref.Object.Type == "commit" {
			break
		}
		if ref.Object.Type != "tag" || depth >= 5 {
			return empty, fmt.Errorf("target tag does not resolve to a commit")
		}
		endpoint := base + "/git/tags/" + ref.Object.SHA
		ref.Object.Type, ref.Object.SHA = "", ""
		if err := compatibilityJSON(ctx, client, endpoint, &ref); err != nil {
			return empty, err
		}
	}
	var file struct {
		Encoding string `json:"encoding"`
		Content  string `json:"content"`
	}
	if err := compatibilityJSON(ctx, client, base+"/contents/compatibility.json?ref="+ref.Object.SHA, &file); err != nil {
		return empty, err
	}
	if file.Encoding != "base64" {
		return empty, fmt.Errorf("unexpected compatibility metadata encoding")
	}
	data, err := base64.StdEncoding.DecodeString(file.Content)
	if err != nil {
		return empty, fmt.Errorf("invalid compatibility content: %w", err)
	}
	p, err := compatibility.Parse(data)
	if err != nil {
		return empty, fmt.Errorf("invalid target compatibility policy: %w", err)
	}
	return p, nil
}

func compatibilityJSON(ctx context.Context, client *http.Client, endpoint string, dest any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "puda-cli-updater")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("target compatibility metadata HTTP %s", resp.Status)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, compatibilityMaxBytes+1))
	if err != nil {
		return err
	}
	if len(data) > compatibilityMaxBytes {
		return fmt.Errorf("target compatibility metadata exceeds size limit")
	}
	if err := json.Unmarshal(data, dest); err != nil {
		return fmt.Errorf("invalid target metadata response: %w", err)
	}
	return nil
}
