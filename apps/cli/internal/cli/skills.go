package cli

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
)

const skillsNodeURL = "https://nodejs.org/en/download"
const pudaSkillsRepo = "PUDAP/skills"
const streamlitSkillsRepo = "streamlit/agent-skills"

// skillsCmd is the parent for OpenSkills-related subcommands
var skillsCmd = &cobra.Command{
	Use:   "skills",
	Short: "Manage puda agent skills",
	Long:  `Install and update OpenSkills for this project. Requires Node.js.`,
}

// skillsInstallCmd installs and syncs OpenSkills
var skillsInstallCmd = &cobra.Command{
	Use:   "install",
	Short: "Install and sync OpenSkills",
	Long: `Install OpenSkills from PUDAP/skills and streamlit/agent-skills, then sync to AGENTS.md (non-interactive).

Runs:
  npx openskills install PUDAP/skills --yes
  npx openskills install streamlit/agent-skills --yes
  npx openskills sync --yes

Node.js required: ` + skillsNodeURL,
	RunE: runSkillsInstall,
}

// skillsUpdateCmd refreshes skills from repo and syncs AGENTS.md
var skillsUpdateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update OpenSkills and sync AGENTS.md",
	Long: `Refresh skills from the repo and update AGENTS.md.

Runs: npx openskills update`,
	RunE: runSkillsUpdate,
}

func init() {
	skillsCmd.AddCommand(skillsInstallCmd)
	skillsCmd.AddCommand(skillsUpdateCmd)
	rootCmd.AddCommand(skillsCmd)
}

func ensureNpx() error {
	if _, err := exec.LookPath("npx"); err != nil {
		fmt.Fprintf(os.Stderr, "Error: npx not found. OpenSkills requires Node.js.\n")
		fmt.Fprintf(os.Stderr, "Install Node.js from: %s\n", skillsNodeURL)
		return err
	}
	return nil
}

func runNpx(args ...string) error {
	c := exec.Command("npx", args...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin
	return c.Run()
}

// installSkillsInCwd installs and syncs OpenSkills in the current working directory.
// Used by both "puda skills install" and "puda init".
func installSkillsInCwd() error {
	if err := ensureNpx(); err != nil {
		return err
	}
	if err := runNpx("openskills", "install", pudaSkillsRepo, "--yes"); err != nil {
		return fmt.Errorf("openskills install failed: %w", err)
	}
	if err := runNpx("openskills", "install", streamlitSkillsRepo, "--yes"); err != nil {
		return fmt.Errorf("openskills install %s failed: %w", streamlitSkillsRepo, err)
	}
	if err := runNpx("openskills", "sync", "--yes"); err != nil {
		return fmt.Errorf("openskills sync failed: %w", err)
	}
	return nil
}

func runSkillsInstall(cmd *cobra.Command, args []string) error {
	if err := installSkillsInCwd(); err != nil {
		return err
	}
	fmt.Fprintf(cmd.OutOrStdout(), "PUDA skills installed and synced successfully.\n")
	return nil
}

func runSkillsUpdate(cmd *cobra.Command, args []string) error {
	if err := ensureNpx(); err != nil {
		return err
	}
	if err := runNpx("openskills", "update"); err != nil {
		return fmt.Errorf("openskills update failed: %w", err)
	}
	return nil
}
