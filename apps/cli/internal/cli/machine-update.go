package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var (
	updateSourceType   string
	updateRef          string
	updateTimeout      int
	updateAliveTimeout int
)

var machineUpdateCmd = &cobra.Command{
	Use:   "update <machine_id>",
	Short: "Send an update command to a PUDA edge over NATS",
	Long: `Publish an update command to puda.<machine_id>.update (core NATS, no
JetStream) instructing the edge to pull new code from git or docker and
restart itself.

The edge subscribes to puda.<machine_id>.update and, on success, publishes a
response on puda.<machine_id>.update.response before disconnecting and
re-executing. The response message IS the confirmation that the pull worked;
no second "restart done" message is published.

For git updates, --ref is optional and accepts a GitHub-style URL. When
provided, the edge re-points "origin" to that URL before fetching. An optional
"/tree/<ref>" segment selects a branch, tag, or commit SHA; without it the
edge resets to the "main" branch. When --ref is omitted, the edge fetches
from its existing "origin" and resets to "main".

For docker updates, --ref is required and is the image:tag to pull.

Examples:
  # Fetch from the existing origin, reset to main
  puda machine update edge-test

  # Point at a different repo + branch (slashes in the branch name are fine)
  puda machine update edge-test \
      --ref https://github.com/PUDAP/puda/tree/feat/edge-update-command

  # Point at a different repo, default branch (main)
  puda machine update edge-test \
      --ref https://github.com/PUDAP/puda

  # Reset to a specific commit
  puda machine update edge-test \
      --ref https://github.com/PUDAP/puda/tree/776213a920a11a15ce6512e0a2a5f6afc70bf85e

  # Docker update
  puda machine update edge-test \
      --source-type docker \
      --ref ghcr.io/pudap/machine-template:latest`,
	Args: cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return runMachineUpdate(args[0])
	},
}

func init() {
	machineUpdateCmd.Flags().StringVar(&updateSourceType, "source-type", "git", "Update source type: 'git' or 'docker'")
	machineUpdateCmd.Flags().StringVar(&updateRef, "ref", "", "Git URL (optional; with /tree/<branch|tag|sha>) or docker image:tag (required for docker)")
	machineUpdateCmd.Flags().IntVar(&updateTimeout, "timeout", 60, "Seconds to wait for the edge's update response")
	machineUpdateCmd.Flags().IntVar(&updateAliveTimeout, "alive-timeout", 5, "Seconds to wait for a heartbeat before publishing the update")

	machineCmd.AddCommand(machineUpdateCmd)
}

// parseGitRef splits a GitHub-style URL into its repo URL and optional
// checkout (branch, tag, or commit SHA) by looking for a "/tree/<ref>" segment.
// The ref may contain further slashes (e.g. "feat/edge-update-command").
func parseGitRef(raw string) (repoURL, checkout string) {
	const sep = "/tree/"
	trimmed := strings.TrimRight(raw, "/")
	idx := strings.Index(trimmed, sep)
	if idx < 0 {
		return trimmed, ""
	}
	return strings.TrimRight(trimmed[:idx], "/"), strings.Trim(trimmed[idx+len(sep):], "/")
}

func runMachineUpdate(machineID string) error {
	globalConfig, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
	}
	userID := globalConfig.User.UserID
	username := globalConfig.User.Username
	if userID == "" || username == "" {
		return fmt.Errorf("user not logged in. Please run 'puda login' first")
	}

	switch updateSourceType {
	case "git", "docker":
	default:
		return fmt.Errorf("invalid --source-type %q: expected 'git' or 'docker'", updateSourceType)
	}

	params := pudanats.UpdateParams{SourceType: updateSourceType}
	switch updateSourceType {
	case "git":
		if updateRef != "" {
			params.Ref, params.Checkout = parseGitRef(updateRef)
		}
	case "docker":
		if updateRef == "" {
			return fmt.Errorf("--ref is required for docker updates")
		}
		params.Ref = updateRef
	}

	nc, err := connectMachineNATS()
	if err != nil {
		return err
	}
	defer nc.Close()

	aliveTimeout := time.Duration(updateAliveTimeout) * time.Second
	fmt.Fprintf(os.Stdout, "Waiting up to %s for heartbeat from %s ...\n", aliveTimeout, machineID)
	if err := pudanats.WaitForHeartbeat(nc, machineID, aliveTimeout); err != nil {
		return err
	}

	if updateSourceType == "git" {
		refDesc := params.Ref
		if refDesc == "" {
			refDesc = "<edge origin>"
		}
		if params.Checkout != "" {
			fmt.Fprintf(os.Stdout, "Publishing update to %s (source_type=git, ref=%s, checkout=%s)\n", machineID, refDesc, params.Checkout)
		} else {
			fmt.Fprintf(os.Stdout, "Publishing update to %s (source_type=git, ref=%s)\n", machineID, refDesc)
		}
	} else {
		fmt.Fprintf(os.Stdout, "Publishing update to %s (source_type=%s, ref=%s)\n", machineID, updateSourceType, params.Ref)
	}
	reply, err := pudanats.SendUpdateCommand(
		nc, machineID, userID, username, params, time.Duration(updateTimeout)*time.Second,
	)
	if err != nil {
		return err
	}

	if reply == nil || reply.Response == nil {
		return fmt.Errorf("malformed update response")
	}

	summary := map[string]interface{}{
		"status":  string(reply.Response.Status),
		"message": reply.Response.Message,
		"data":    reply.Response.Data,
	}
	if reply.Response.Code != nil {
		summary["code"] = *reply.Response.Code
	}
	encoded, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to encode update summary: %w", err)
	}
	fmt.Println(string(encoded))

	if reply.Response.Status != puda.StatusSuccess {
		msg := "unknown error"
		if reply.Response.Message != nil {
			msg = *reply.Response.Message
		}
		return fmt.Errorf("update failed: %s", msg)
	}
	return nil
}
